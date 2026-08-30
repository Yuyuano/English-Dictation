# English Dictation · 英语听写练习

一个离线的 Windows 桌面听写工具：选择词库 → 程序朗读单词（TTS）→ 你拼写 → 自动按「词库 × 单词」维度累计正确率。

基于 **PySide6 (Qt6)** 界面 + **pyttsx3** 离线语音 + **SQLite** 统计，无需联网。

## 功能

- **词库管理**：导入 / 新建 / 编辑 / 导出 JSON 词库（存放于 `Libraries/*.json`）
- **听写练习**：随机顺序出题，行内即时反馈，答错可重写练习（不计分）
- **结果页**：正确率汇总、错词回顾、一键「错词重练」「再来一轮」
- **统计**：逐词正确率表格，薄弱词排最前
- **细节**：单词搜索过滤、逐词发音按钮、语速调节（持久化）、答案规范化比较（`apple.` 不判错）
- 数据兼容：沿用旧版 `stats.db` 表结构与词库 JSON 格式，升级即用

## 运行

```bash
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt   # Windows
.venv/Scripts/python.exe tests/test_core.py     # 可选：跑核心逻辑单元测试
.venv/Scripts/python.exe main.py
```

## 打包为 exe

```bash
.venv/Scripts/pip install pyinstaller
.venv/Scripts/pyinstaller main.spec
# 产物：dist/EnglishDictation.exe
```

## 项目结构

```
main.py               入口：装配依赖、启动 Qt 主循环
app/
  config.py           路径解析、默认参数、settings.json 持久化
  models.py           Word / Library 值对象
  answer.py           答案规范化纯函数
  dictation.py        听写轮次状态机（纯逻辑，可独立测试）
  storage.py          词库 JSON 仓储 + SQLite 统计仓储
  tts.py              语音服务（常驻单 worker 线程，播放请求串行、可打断）
  ui/                 PySide6 界面层（主窗口 / 词库编辑 / 统计 / 听写）
tests/test_core.py    核心逻辑单元测试（无 pytest 依赖，直接运行）
```

架构原则：`app/` 中除 `ui/` 外的模块**不依赖 Qt**，核心逻辑（状态机、仓储、答案判定）全部可脱离界面单独测试。

## 词库格式

```json
{
  "words": [
    { "word": "apple", "meaning": "苹果" },
    { "word": "look forward to", "meaning": "期待；盼望" }
  ]
}
```
