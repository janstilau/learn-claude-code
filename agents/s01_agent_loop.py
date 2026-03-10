#!/usr/bin/env python3
"""
s01_agent_loop.py - Agent 循环

AI 编码代理的核心秘密就在这一个模式中：

    while stop_reason == "tool_use":
        response = LLM(messages, tools)
        execute tools
        append results

    +----------+      +-------+      +---------+
    |   User   | ---> |  LLM  | ---> |  Tool   |
    |  prompt  |      |       |      | execute |
    +----------+      +---+---+      +----+----+
                          ^               |
                          |   tool_result |
                          +---------------+
                          (loop continues)

这是核心循环：将工具结果反馈给模型，
直到模型决定停止。生产级代理在此基础上
叠加了策略、钩子和生命周期控制。
"""

import os
import subprocess
import json
import time
from datetime import datetime

from anthropic import Anthropic
from dotenv import load_dotenv

# 导入新的日志工具
import logtool

load_dotenv(override=True)

if os.getenv("ANTHROPIC_BASE_URL"):
    os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)

client = Anthropic(base_url=os.getenv("ANTHROPIC_BASE_URL"))
MODEL = os.environ["MODEL_ID"]
logger = logtool.get_logger()

SYSTEM = f"你是一个位于 {os.getcwd()} 的编码代理。使用 bash 来解决任务。直接行动，不要解释。"

TOOLS = [{
    "name": "bash",
    "description": "运行 shell 命令。",
    "input_schema": {
        "type": "object",
        "properties": {"command": {"type": "string"}},
        "required": ["command"],
    },
}]


def run_bash(command: str) -> str:
    dangerous = ["rm -rf /", "sudo", "shutdown", "reboot", "> /dev/"]
    if any(d in command for d in dangerous):
        return "错误：危险命令被拦截"
    try:
        r = subprocess.run(command, shell=True, cwd=os.getcwd(),
                           capture_output=True, text=True, timeout=120)
        out = (r.stdout + r.stderr).strip()
        return out[:50000] if out else "(无输出)"
    except subprocess.TimeoutExpired:
        return "错误：超时 (120秒)"


# -- 核心模式：一个 while 循环调用工具直到模型停止 --
def agent_loop(messages: list):
    while True:
        # 准备请求数据
        request_data = {
            "model": MODEL,
            "system": SYSTEM,
            "messages": messages, # 注意：这里的 messages 是引用，随着循环会变，但在此时是快照
            "tools": TOOLS
        }
        
        response = client.messages.create(
            model=MODEL, system=SYSTEM, messages=messages,
            tools=TOOLS, max_tokens=8000,
        )
        
        # 准备响应数据
        response_data = {
            "stop_reason": response.stop_reason,
            "content": [block.model_dump() for block in response.content],
            "usage": response.usage.model_dump()
        }
        
        # 写入日志
        logger.log_interaction(request_data, response_data)

        logtool.print_model_response_header()
        
        for block in response.content:
            if block.type == "text":
                logtool.print_model_text(block.text)
            elif block.type == "tool_use":
                logtool.print_tool_use(block.input)

        # 追加助手回合（将 Pydantic 对象转换为字典）
        messages.append({"role": "assistant", "content": [
            block.model_dump() for block in response.content
        ]})
        # 如果模型没有调用工具，我们就完成了
        if response.stop_reason != "tool_use":
            return
        # 执行每个工具调用，收集结果
        results = []
        for block in response.content:
            if block.type == "tool_use":
                output = run_bash(block.input["command"])
                logtool.print_tool_result(output)
                results.append({"type": "tool_result", "tool_use_id": block.id,
                                "content": output})
        messages.append({"role": "user", "content": results})


if __name__ == "__main__":
    history = []
    while True:
        try:
            logtool.print_user("") # 仅为了一致性，这里主要还是 input 提示
            query = input(f"{logtool.Colors.CYAN}s01 >> {logtool.Colors.RESET}")
        except (EOFError, KeyboardInterrupt):
            break
        if query.strip().lower() in ("q", "exit", ""):
            break
        history.append({"role": "user", "content": query})
        agent_loop(history)
        print()
