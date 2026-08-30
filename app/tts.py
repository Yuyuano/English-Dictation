"""语音服务。

旧版的问题：引擎在主线程创建，每次播放又各起一个新线程调 runAndWait()，
连点即触发 "run loop already started" 崩溃；而"播放所选"又在主线程同步播放，
导致界面假死。

本服务改为：一个常驻 worker 线程独占 pyttsx3 引擎（引擎在该线程内创建，
规避 Windows COM 套间线程亲和问题），播放请求经队列串行执行，
新请求会打断旧朗读并清空积压队列。

播放底层不用 runAndWait()：引擎空闲时调用它，其内部的 endLoop 标记命令
会在语音起播几毫秒内被事件循环执行，把刚开始的朗读 purge 掉（pyttsx3
2.99 已知缺陷，表现为"第二次及以后点击播放没声音"）。改为
say() + startLoop()/endLoop() 手动泵事件循环，见 _speak_once()。

QObject/Signal 仅用于向 Qt 主线程回传播放状态与错误，核心不依赖它也可测试。
"""
from __future__ import annotations

import logging
import queue
import sys
import threading
from typing import Optional, Tuple

from PySide6.QtCore import QObject, Signal

from .config import TTS_DEFAULT_RATE, TTS_DEFAULT_VOLUME

logger = logging.getLogger(__name__)


class SpeakerService(QObject):
    """线程安全的离线语音服务。所有公开方法均可在任意线程调用。"""

    stateChanged = Signal(str)      # "speaking" / "idle"
    errorOccurred = Signal(str)     # 文案可直接展示给用户

    def __init__(self, rate: int = TTS_DEFAULT_RATE, volume: float = TTS_DEFAULT_VOLUME):
        super().__init__()
        self._queue: "queue.Queue[Optional[Tuple[str, int]]]" = queue.Queue()
        self._rate = max(60, min(260, int(rate)))
        self._volume = float(volume)
        self._interrupt = threading.Event()
        self._engine = None                 # 仅 worker 线程内使用
        self._thread = threading.Thread(target=self._worker, name="tts-worker", daemon=True)
        self._thread.start()

    # ---------- 公开接口（主线程调用） ----------
    def set_rate(self, rate: int) -> None:
        self._rate = max(60, min(260, int(rate)))

    def speak(self, text: str, repeat: int = 1) -> None:
        """打断当前朗读并播放 text。"""
        text = (text or "").strip()
        if not text:
            return
        self._drain_queue()
        self._interrupt.set()
        engine = self._engine
        if engine is not None:
            try:
                engine.stop()   # pyttsx3 支持跨线程 stop()，用于打断当前 runAndWait
            except Exception:
                logger.debug("engine.stop() 调用失败", exc_info=True)
        self._queue.put((text, max(1, int(repeat))))

    def shutdown(self) -> None:
        """停止播放并退出 worker 线程。"""
        self._drain_queue()
        self._queue.put(None)
        engine = self._engine
        if engine is not None:
            try:
                engine.stop()
            except Exception:
                pass

    # ---------- 内部 ----------
    def _drain_queue(self) -> None:
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                return

    def _worker(self) -> None:
        self._init_com()
        try:
            import pyttsx3

            engine = pyttsx3.init()
            engine.setProperty("volume", self._volume)
            self._engine = engine
        except Exception as e:
            logger.exception("TTS 引擎初始化失败")
            self.errorOccurred.emit(f"语音引擎初始化失败，发音功能不可用：{e}")
            # 不 return：继续消费队列，保证 speak() 永不阻塞调用方

        while True:
            item = self._queue.get()
            if item is None:
                break
            if self._engine is None:
                continue
            text, repeat = item
            self._interrupt.clear()
            self.stateChanged.emit("speaking")
            try:
                self._engine.setProperty("rate", self._rate)  # 每条请求应用最新语速
                for i in range(repeat):
                    if self._interrupt.is_set():
                        break
                    self._speak_once(self._engine, text)
                    if i < repeat - 1 and self._interrupt.wait(0.25):
                        break   # 等待重复间隔期间被新请求打断
            except Exception as e:
                logger.exception("朗读失败")
                self.errorOccurred.emit(f"朗读失败：{e}")
            finally:
                self.stateChanged.emit("idle")

    @staticmethod
    def _speak_once(engine, text: str) -> None:
        """朗读一段并阻塞到该段结束。

        禁止改成 engine.runAndWait()，原因见模块 docstring。
        EndStream（语音结束）事件只在消息泵内分发，say() 与 startLoop()
        之间不泵消息，因此不存在"语音已结束才进入循环"的竞态。
        """
        engine.say(text)
        engine.startLoop()   # 阻塞泵 COM 消息，直到 EndStream 结束循环
        engine.endLoop()     # 复位 engine 的 _inLoop 状态；此刻 speaking 已为 False，无 purge

    @staticmethod
    def _init_com() -> None:
        """COM 按线程初始化：SAPI 的 COM 对象在本线程创建前必须先初始化。

        之前靠"worker 线程恰好第一个 import pyttsx3/comtypes"的导入顺序
        隐式完成，打包或调整导入后就会炸，这里显式声明。
        """
        if sys.platform != "win32":
            return
        try:
            import comtypes

            comtypes.CoInitialize()
        except ImportError:
            pass
        except OSError:
            logger.debug("CoInitialize 失败（可能已按其他模式初始化）", exc_info=True)
