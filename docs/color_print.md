# Agent 控制台颜色规范

本文档定义了 Agent 交互过程中控制台输出的颜色规范，旨在提供清晰、一致的视觉体验。

## 颜色定义

我们使用 ANSI 转义序列来控制颜色。

| 组件 | 颜色 | ANSI 代码 | 描述 |
| :--- | :--- | :--- | :--- |
| **User Input** | <span style="color:cyan">Cyan (青色)</span> | `\033[36m` | 用户输入的提示符及内容 |
| **Model Header** | **Bold (加粗)** | `\033[1m` | 模型响应的分割线 (`--- model_response ---`) |
| **Model Response** | <span style="color:orange">Orange (橙色)</span> | `\033[38;5;208m` | 模型生成的普通文本内容 |
| **Tool Use** | <span style="color:yellow">Yellow (黄色)</span> | `\033[33m` | 模型调用的工具名称及参数 |
| **Tool Result** | <span style="color:green">Green (绿色)</span> | `\033[32m` | 工具执行后的返回结果 |
| **System/Info** | <span style="color:gray">Gray (灰色)</span> | `\033[90m` | 系统日志路径、调试信息等 |
| **Error** | <span style="color:red">Red (红色)</span> | `\033[31m` | 错误消息、异常堆栈 |

## 实现参考

请参考 `agents/logtool.py` 中的 `Colors` 类和打印函数。

```python
class Colors:
    CYAN = "\033[36m"       # User
    ORANGE = "\033[38;5;208m" # Model Response
    YELLOW = "\033[33m"     # Tool Use
    GREEN = "\033[32m"      # Tool Result
    # ...
```

## 示例

```text
(Cyan) s01 >> (User Input)

(Bold) --- model_response ---

(Orange) 好的，我来执行这个任务。
(Yellow) Tool Use: {'command': 'ls -la'}

(Green) Tool Result: total 0 ...
```
