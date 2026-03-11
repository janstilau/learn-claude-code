#!/usr/bin/env python3
"""s03_todo_write.py - 待办事项写入

模型通过 TodoManager 跟踪自己的进度。
当它忘记更新时，会有一个提醒机制强制它更新。

    +----------+      +-------+      +---------+
    |   User   | ---> |  LLM  | ---> | Tools   |
    |  prompt  |      |       |      | + todo  |
    +----------+      +---+---+      +----+----+
                          ^               |
                          |   tool_result |
                          +---------------+
                                |
                    +-----------+-----------+
                    | TodoManager state     |
                    | [ ] task A            |
                    | [>] task B <- doing   |
                    | [x] task C            |
                    +-----------------------+
                                |
                    if rounds_since_todo >= 3:
                      inject <reminder>

核心见解：“代理可以跟踪自己的进度——而且我能看到。”
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

# 提示词里面, 就有了变化.
# 下面专门增加一个 todo 工具, 提示词这里才会有这个工具的注入.
SYSTEM = f"""你是一个位于 {WORKDIR} 的编码代理。
使用 todo 工具来规划多步骤任务。开始前标记为 in_progress，完成后标记为 completed。
优先使用工具而不是文字描述。"""


# -- TodoManager: LLM 写入的结构化状态 --
class TodoManager:
    def __init__(self):
        self.items = []

    def update(self, items: list) -> str:
        if len(items) > 20:
            raise ValueError("最多允许 20 个待办事项")
        validated = []
        in_progress_count = 0
        for i, item in enumerate(items):
            text = str(item.get("text", "")).strip()
            status = str(item.get("status", "pending")).lower()
            item_id = str(item.get("id", str(i + 1)))
            if not text:
                raise ValueError(f"项目 {item_id}: 需要文本内容")
            if status not in ("pending", "in_progress", "completed"):
                raise ValueError(f"项目 {item_id}: 无效状态 '{status}'")
            if status == "in_progress":
                in_progress_count += 1
            validated.append({"id": item_id, "text": text, "status": status})
        if in_progress_count > 1:
            raise ValueError("每次只能有一个任务处于进行中")
        self.items = validated
        return self.render()

    def render(self) -> str:
        if not self.items:
            return "无待办事项。"
        lines = []
        for item in self.items:
            marker = {"pending": "[ ]", "in_progress": "[>]", "completed": "[x]"}[item["status"]]
            lines.append(f"{marker} #{item['id']}: {item['text']}")
        done = sum(1 for t in self.items if t["status"] == "completed")
        lines.append(f"\n({done}/{len(self.items)} 完成)")
        return "\n".join(lines)


TODO = TodoManager()


# -- 工具实现 --
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
    "todo":       lambda **kw: TODO.update(kw["items"]),
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
    {"name": "todo", "description": "更新任务列表。跟踪多步骤任务的进度。",
     "input_schema": {"type": "object", "properties": {"items": {"type": "array", "items": {"type": "object", "properties": {"id": {"type": "string"}, "text": {"type": "string"}, "status": {"type": "string", "enum": ["pending", "in_progress", "completed"]}}, "required": ["id", "text", "status"]}}}, "required": ["items"]}},
]


# -- 带有提醒注入的代理循环 --
def agent_loop(messages: list):
    rounds_since_todo = 0
    while True:
        # 准备请求数据
        request_data = {
            "model": MODEL,
            "system": SYSTEM,
            "messages": messages,
            "tools": TOOLS,
        }

        # 提醒在下面注入，与工具结果一起
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
        used_todo = False
        for block in response.content:
            if block.type == "tool_use":
                handler = TOOL_HANDLERS.get(block.name)
                try:
                    output = handler(**block.input) if handler else f"未知工具：{block.name}"
                except Exception as e:
                    output = f"错误：{e}"
                logtool.print_tool_result(str(output))
                results.append({"type": "tool_result", "tool_use_id": block.id, "content": str(output)})
                if block.name == "todo":
                    used_todo = True

        # 确保所有工具调用都有结果
        # 按顺序补齐缺失的结果，确保顺序一致
        final_results = []
        for block in response.content:
            if block.type == "tool_use":
                # 寻找已经存在的结果
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

        rounds_since_todo = 0 if used_todo else rounds_since_todo + 1
        # 专门插入了一句, 提示模型要去更新任务的状态
        if rounds_since_todo >= 3:
            # 将 reminder 放在结果之后，避免某些解析器提前终止
            final_results.append({"type": "text", "text": "\n<reminder>更新你的待办事项。</reminder>"})
        messages.append({"role": "user", "content": final_results})


if __name__ == "__main__":
    history = []
    while True:
        try:
            logtool.print_user("")
            query = input(f"{logtool.Colors.CYAN}s03 >> {logtool.Colors.RESET}")
        except (EOFError, KeyboardInterrupt):
            break
        if query.strip().lower() in ("q", "exit", ""):
            break
        history.append({"role": "user", "content": query})
        agent_loop(history)
        print()
