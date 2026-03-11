#!/usr/bin/env python3
"""s06_context_compact.py - 上下文压缩

三层压缩管道，使代理能够永远工作下去：

    Every turn:
    +------------------+
    | Tool call result |
    +------------------+
            |
            v
    [Layer 1: micro_compact]        (silent, every turn)
      Replace tool_result content older than last 3
      with "[Previous: used {tool_name}]"
            |
            v
    [Check: tokens > 50000?]
       |               |
       no              yes
       |               |
       v               v
    continue    [Layer 2: auto_compact]
                  Save full transcript to .transcripts/
                  Ask LLM to summarize conversation.
                  Replace all messages with [summary].
                        |
                        v
                [Layer 3: compact tool]
                  Model calls compact -> immediate summarization.
                  Same as auto, triggered manually.

核心见解：“代理可以策略性地遗忘并永远工作下去。”
"""

import json
import os
import subprocess
import time
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

SYSTEM = f"你是一个位于 {WORKDIR} 的编码代理。使用工具来解决任务。"

THRESHOLD = 50000
TRANSCRIPT_DIR = WORKDIR / ".transcripts"
KEEP_RECENT = 3


def estimate_tokens(messages: list) -> int:
    """Rough token count: ~4 chars per token."""
    return len(str(messages)) // 4


# -- Layer 1: micro_compact - replace old tool results with placeholders --
def micro_compact(messages: list) -> list:
    # Collect (msg_index, part_index, tool_result_dict) for all tool_result entries
    tool_results = []
    for msg_idx, msg in enumerate(messages):
        if msg["role"] == "user" and isinstance(msg.get("content"), list):
            for part_idx, part in enumerate(msg["content"]):
                if isinstance(part, dict) and part.get("type") == "tool_result":
                    tool_results.append((msg_idx, part_idx, part))
    if len(tool_results) <= KEEP_RECENT:
        return messages
    # Find tool_name for each result by matching tool_use_id in prior assistant messages
    tool_name_map = {}
    for msg in messages:
        if msg["role"] == "assistant":
            content = msg.get("content", [])
            if isinstance(content, list):
                for block in content:
                    if hasattr(block, "type") and block.type == "tool_use":
                        tool_name_map[block.id] = block.name
    # Clear old results (keep last KEEP_RECENT)
    to_clear = tool_results[:-KEEP_RECENT]
    for _, _, result in to_clear:
        if isinstance(result.get("content"), str) and len(result["content"]) > 100:
            tool_id = result.get("tool_use_id", "")
            tool_name = tool_name_map.get(tool_id, "unknown")
            result["content"] = f"[之前：使用了 {tool_name}]"
    return messages


# -- Layer 2: auto_compact - save transcript, summarize, replace messages --
def auto_compact(messages: list) -> list:
    # Save full transcript to disk
    TRANSCRIPT_DIR.mkdir(exist_ok=True)
    transcript_path = TRANSCRIPT_DIR / f"transcript_{int(time.time())}.jsonl"
    with open(transcript_path, "w") as f:
        for msg in messages:
            f.write(json.dumps(msg, default=str) + "\n")
            
# 会把原来的数据, 存储起来, 然后调用大模型进行总结. 
    logtool.print_info(f"[对话记录已保存：{transcript_path}]")
    # Ask LLM to summarize
    conversation_text = json.dumps(messages, default=str)[:80000]
    response = client.messages.create(
        model=MODEL,
        messages=[{"role": "user", "content":
            "为了保持连续性，请总结这段对话。包括："
            "1) 完成了什么，2) 当前状态，3) 做出的关键决定。"
            "简明扼要，但保留关键细节。\n\n" + conversation_text}],
        max_tokens=2000,
    )
    summary = response.content[0].text
    # Replace all messages with compressed summary
    return [
        {"role": "user", "content": f"[对话已压缩。记录：{transcript_path}]\n\n{summary}"},
        {"role": "assistant", "content": "收到。我已获取摘要中的上下文。继续。"},
    ]


# -- Tool implementations --
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
    "compact":    lambda **kw: "已请求手动压缩。",
}

TOOLS = [
    {"name": "bash", "description": "运行 shell 命令。",
     "input_schema": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}},
    {"name": "read_file", "description": "读取文件内容。",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "limit": {"type": "integer"}}, "required": ["path"]}},
    {"name": "write_file", "description": "写入内容到文件。",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}},
    {"name": "edit_file", "description": "替换文件中的确切文本。",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "old_text": {"type": "string"}, "new_text": {"type": "string"}}, "required": ["path", "old_text", "new_text"]}},
    {"name": "compact", "description": "触发手动对话压缩。",
     "input_schema": {"type": "object", "properties": {"focus": {"type": "string", "description": "在摘要中保留的重点"}}}},
]


def agent_loop(messages: list):
    while True:
        # Layer 1: micro_compact before each LLM call
        # 这个压缩是自动触发的, 这是这个项目的逻辑, 不是真实的逻辑.
        micro_compact(messages)
        # Layer 2: auto_compact if token estimate exceeds threshold
        if estimate_tokens(messages) > THRESHOLD:
            logtool.print_info("[触发自动压缩]")
            messages[:] = auto_compact(messages)

        # 准备请求数据
        request_data = {
            "model": MODEL,
            "system": SYSTEM,
            "messages": messages,
            "tools": TOOLS,
        }

        response = client.messages.create(
            model=MODEL, system=SYSTEM, messages=messages,
            tools=TOOLS, max_tokens=8000,
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
                if block.name == "compact":
                    logtool.print_info("[触发手动压缩]")
# 手动触发的思路, 和自动触发是一样的, 都是调用接口进行触发. 
                    messages[:] = auto_compact(messages)
                    output = "已压缩对话历史。"
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
            query = input(f"{logtool.Colors.CYAN}s06 >> {logtool.Colors.RESET}")
        except (EOFError, KeyboardInterrupt):
            break
        if query.strip().lower() in ("q", "exit", ""):
            break
        history.append({"role": "user", "content": query})
        agent_loop(history)
        print()
