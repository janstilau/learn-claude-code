#!/usr/bin/env python3
"""s04_subagent.py - 子代理

生成一个带有 fresh messages=[] 的子代理。子代理在自己的
上下文中工作，共享文件系统，然后只向父代理返回摘要。

    Parent agent                     Subagent
    +------------------+             +------------------+
    | messages=[...]   |             | messages=[]      |  <-- fresh
    |                  |  dispatch   |                  |
    | tool: task       | ---------->| while tool_use:  |
    |   prompt="..."   |            |   call tools     |
    |   description="" |            |   append results |
    |                  |  summary   |                  |
    |   result = "..." | <--------- | return last text |
    +------------------+             +------------------+
              |
    Parent context stays clean.
    Subagent context is discarded.

核心见解：“进程隔离免费提供了上下文隔离。”
"""

import os
import subprocess
from pathlib import Path

import logtool
from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv(override=True)

if os.getenv("ANTHROPIC_BASE_URL"):
    os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)

WORKDIR = Path.cwd()
client = Anthropic(base_url=os.getenv("ANTHROPIC_BASE_URL"))
MODEL = os.environ["MODEL_ID"]
logger = logtool.get_logger()

SYSTEM = f"你是一个位于 {WORKDIR} 的编码代理。使用 task 工具来委派探索或子任务。"
SUBAGENT_SYSTEM = f"你是一个位于 {WORKDIR} 的编码子代理。完成给定的任务，然后总结你的发现。"


# -- 父代理和子代理共享的工具实现 --
def safe_path(p: str) -> Path:
    path = (WORKDIR / p).resolve()
    if not path.is_relative_to(WORKDIR):
        raise ValueError(f"路径超出工作区范围：{p}")
    return path

def run_bash(command: str) -> str:
    dangerous = ["rm -rf /", "sudo", "shutdown", "reboot", "> /dev/"]
    if any(d in command for d in dangerous):
        return "错误：危险命令被拦截"
    try:
        r = subprocess.run(command, shell=True, cwd=WORKDIR,
                           capture_output=True, text=True, timeout=120, check=False)
        out = (r.stdout + r.stderr).strip()
        return out[:50000] if out else "(无输出)"
    except subprocess.TimeoutExpired:
        return "错误：超时 (120秒)"

def run_read(path: str, limit: int = None) -> str:
    try:
        lines = safe_path(path).read_text().splitlines()
        if limit and limit < len(lines):
            lines = lines[:limit] + [f"... (还有 {len(lines) - limit} 行)"]
        return "\n".join(lines)[:50000]
    except Exception as e:
        return f"错误：{e}"

def run_write(path: str, content: str) -> str:
    try:
        fp = safe_path(path)
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content)
        return f"已写入 {len(content)} 字节"
    except Exception as e:
        return f"错误：{e}"

def run_edit(path: str, old_text: str, new_text: str) -> str:
    try:
        fp = safe_path(path)
        content = fp.read_text()
        if old_text not in content:
            return f"错误：在 {path} 中未找到文本"
        fp.write_text(content.replace(old_text, new_text, 1))
        return f"已编辑 {path}"
    except Exception as e:
        return f"错误：{e}"


TOOL_HANDLERS = {
    "bash":       lambda **kw: run_bash(kw["command"]),
    "read_file":  lambda **kw: run_read(kw["path"], kw.get("limit")),
    "write_file": lambda **kw: run_write(kw["path"], kw["content"]),
    "edit_file":  lambda **kw: run_edit(kw["path"], kw["old_text"], kw["new_text"]),
}

# 子代理获得除 task 外的所有基础工具（无递归生成）
CHILD_TOOLS = [
    {"name": "bash", "description": "运行 shell 命令。",
     "input_schema": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}},
    {"name": "read_file", "description": "读取文件内容。",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "limit": {"type": "integer"}}, "required": ["path"]}},
    {"name": "write_file", "description": "写入内容到文件。",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}},
    {"name": "edit_file", "description": "替换文件中的确切文本。",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "old_text": {"type": "string"}, "new_text": {"type": "string"}}, "required": ["path", "old_text", "new_text"]}},
]


# -- 子代理：全新的上下文，过滤后的工具，仅返回摘要 --
def run_subagent(prompt: str) -> str:
    sub_messages = [{"role": "user", "content": prompt}]  # fresh context
    for _ in range(30):  # safety limit
        # 准备请求数据
        request_data = {
            "model": MODEL,
            "system": SUBAGENT_SYSTEM,
            "messages": sub_messages,
            "tools": CHILD_TOOLS,
        }

        response = client.messages.create(
            model=MODEL, system=SUBAGENT_SYSTEM, messages=sub_messages,
            tools=CHILD_TOOLS, max_tokens=8000,
        )

        # 准备响应数据
        response_data = {
            "stop_reason": response.stop_reason,
            "content": [block.model_dump() for block in response.content],
            "usage": response.usage.model_dump(),
        }

        # 写入日志
        logger.log_interaction(request_data, response_data)

        # 子代理的输出也打印，方便调试
        print(f"\n{logtool.Colors.MAGENTA}[Subagent] model_response:{logtool.Colors.RESET}")
        for block in response.content:
            if block.type == "text":
                logtool.print_model_text(block.text)
            elif block.type == "tool_use":
                logtool.print_tool_use(block.name, block.input)

        sub_messages.append({"role": "assistant", "content": [
            block.model_dump() for block in response.content
        ]})
        if response.stop_reason != "tool_use":
            break
        results = []
        for block in response.content:
            if block.type == "tool_use":
                handler = TOOL_HANDLERS.get(block.name)
                output = handler(**block.input) if handler else f"未知工具：{block.name}"
                logtool.print_tool_result(str(output))
                results.append({"type": "tool_result", "tool_use_id": block.id, "content": str(output)[:50000]})
        
        # 确保所有工具调用都有结果
        final_results = []
        for block in response.content:
            if block.type == "tool_use":
                found = False
                for r in results:
                    if r["tool_use_id"] == block.id:
                        final_results.append(r)
                        found = True
                        break
                if not found:
                    final_results.append({"type": "tool_result", "tool_use_id": block.id, "content": "错误：工具执行失败或被跳过"})
        
        # 兼容性修复：添加 OpenAI 风格的 tool_call_id
        for res in final_results:
            if "tool_use_id" in res:
                res["tool_call_id"] = res["tool_use_id"]
             
        sub_messages.append({"role": "user", "content": final_results})
    # 只有最终文本返回给父代理——子代理上下文被丢弃
    return "".join(b.text for b in response.content if hasattr(b, "text")) or "(无摘要)"


# -- 父代理工具：基础工具 + 任务调度器 --
PARENT_TOOLS = CHILD_TOOLS + [
    {"name": "task", "description": "生成一个具有全新上下文的子代理。它共享文件系统但不共享对话历史。",
     "input_schema": {"type": "object", "properties": {"prompt": {"type": "string"}, "description": {"type": "string", "description": "任务简短描述"}}, "required": ["prompt"]}},
]


def agent_loop(messages: list):
    while True:
        # 准备请求数据
        request_data = {
            "model": MODEL,
            "system": SYSTEM,
            "messages": messages,
            "tools": PARENT_TOOLS,
        }

        response = client.messages.create(
            model=MODEL, system=SYSTEM, messages=messages,
            tools=PARENT_TOOLS, max_tokens=8000,
        )

        # 准备响应数据
        response_data = {
            "stop_reason": response.stop_reason,
            "content": [block.model_dump() for block in response.content],
            "usage": response.usage.model_dump(),
        }

        # 写入日志
        logger.log_interaction(request_data, response_data)

        logtool.print_model_response_header()

        for block in response.content:
            if block.type == "text":
                logtool.print_model_text(block.text)
            elif block.type == "tool_use":
                logtool.print_tool_use(block.name, block.input)

        messages.append({"role": "assistant", "content": [
            block.model_dump() for block in response.content
        ]})
        if response.stop_reason != "tool_use":
            return
        results = []
        for block in response.content:
            if block.type == "tool_use":
                if block.name == "task":
                    desc = block.input.get("description", "subtask")
                    print(f"{logtool.Colors.YELLOW}> task ({desc}): {block.input['prompt'][:80]}{logtool.Colors.RESET}")
                    output = run_subagent(block.input["prompt"])
                else:
                    handler = TOOL_HANDLERS.get(block.name)
                    output = handler(**block.input) if handler else f"未知工具：{block.name}"
                logtool.print_tool_result(str(output))
                results.append({"type": "tool_result", "tool_use_id": block.id, "content": str(output)})
        
        # 确保所有工具调用都有结果
        final_results = []
        for block in response.content:
            if block.type == "tool_use":
                found = False
                for r in results:
                    if r["tool_use_id"] == block.id:
                        final_results.append(r)
                        found = True
                        break
                if not found:
                    final_results.append({"type": "tool_result", "tool_use_id": block.id, "content": "错误：工具执行失败或被跳过"})
        
        # 兼容性修复：添加 OpenAI 风格的 tool_call_id
        for res in final_results:
            if "tool_use_id" in res:
                res["tool_call_id"] = res["tool_use_id"]
             
        messages.append({"role": "user", "content": final_results})


if __name__ == "__main__":
    history = []
    while True:
        try:
            logtool.print_user("")
            query = input(f"{logtool.Colors.CYAN}s04 >> {logtool.Colors.RESET}")
        except (EOFError, KeyboardInterrupt):
            break
        if query.strip().lower() in ("q", "exit", ""):
            break
        history.append({"role": "user", "content": query})
        agent_loop(history)
        print()
