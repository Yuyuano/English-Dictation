"""English Dictation —— 英语听写练习。

包结构：
- config    路径解析与用户设置
- models    值对象（Word / Library）
- answer    答案规范化纯函数
- dictation 听写轮次状态机（纯逻辑，可独立测试）
- storage   词库(JSON)与统计(SQLite)仓储
- tts       语音服务（常驻单 worker 线程）
- ui        PySide6 界面层
"""

__version__ = "2.0.0"
