"""Tool Templates - 复制并自定义这些用于你的代理。

每个工具需要:
1. 定义 (模型的 JSON 架构)
2. 实现 (Python 函数)
"""

import subprocess
from pathlib import Path

WORKDIR = Path.cwd()


# =============================================================================
# 工具定义 (用于 TOOLS 列表)
# =============================================================================

BASH_TOOL = {
    "name": "bash",
    "description": "运行 shell 命令。用于: ls, find, grep, git, npm, python 等。",
    "input_schema": {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "要执行的 shell 命令",
            },
        },
        "required": ["command"],
    },
}

READ_FILE_TOOL = {
    "name": "read_file",
    "description": "读取文件内容。返回 UTF-8 文本。",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "文件的相对路径",
            },
            "limit": {
                "type": "integer",
                "description": "最大读取行数 (默认: 全部)",
            },
        },
        "required": ["path"],
    },
}

WRITE_FILE_TOOL = {
    "name": "write_file",
    "description": "将内容写入文件。如果需要，创建父目录。",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "文件的相对路径",
            },
            "content": {
                "type": "string",
                "description": "要写入的内容",
            },
        },
        "required": ["path", "content"],
    },
}

EDIT_FILE_TOOL = {
    "name": "edit_file",
    "description": "替换文件中的确切文本。用于精确编辑。",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "文件的相对路径",
            },
            "old_text": {
                "type": "string",
                "description": "要查找的确切文本 (必须精确匹配)",
            },
            "new_text": {
                "type": "string",
                "description": "替换文本",
            },
        },
        "required": ["path", "old_text", "new_text"],
    },
}

TODO_WRITE_TOOL = {
    "name": "TodoWrite",
    "description": "更新任务列表。用于计划和跟踪进度。",
    "input_schema": {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "description": "完整的任务列表",
                "items": {
                    "type": "object",
                    "properties": {
                        "content": {"type": "string", "description": "任务描述"},
                        "status": {"type": "string", "enum": ["pending", "in_progress", "completed"]},
                        "activeForm": {"type": "string", "description": "现在时态，例如 'Reading files'"},
                    },
                    "required": ["content", "status", "activeForm"],
                },
            },
        },
        "required": ["items"],
    },
}

TASK_TOOL_TEMPLATE = """
# Generate dynamically with agent types
TASK_TOOL = {
    "name": "Task",
    "description": f"Spawn a subagent for a focused subtask.\\n\\nAgent types:\\n{get_agent_descriptions()}",
    "input_schema": {
        "type": "object",
        "properties": {
            "description": {"type": "string", "description": "Short task name (3-5 words)"},
            "prompt": {"type": "string", "description": "Detailed instructions"},
            "agent_type": {"type": "string", "enum": list(AGENT_TYPES.keys())},
        },
        "required": ["description", "prompt", "agent_type"],
    },
}
"""


# =============================================================================
# 工具实现
# =============================================================================

def safe_path(p: str) -> Path:
    """Security: Ensure path stays within workspace.
    Prevents ../../../etc/passwd attacks.
    """
    path = (WORKDIR / p).resolve()
    if not path.is_relative_to(WORKDIR):
        raise ValueError(f"路径超出工作区范围: {p}")
    return path


def run_bash(command: str) -> str:
    """Execute shell command with safety checks.

    Safety features:
    - Blocks obviously dangerous commands
    - 60 second timeout
    - Output truncated to 50KB
    """
    dangerous = ["rm -rf /", "sudo", "shutdown", "reboot", "> /dev/"]
    if any(d in command for d in dangerous):
        return "错误: 危险命令已阻止"

    try:
        result = subprocess.run(
            command,
            shell=True,
            cwd=WORKDIR,
            capture_output=True,
            text=True,
            timeout=60, check=False,
        )
        output = (result.stdout + result.stderr).strip()
        return output[:50000] if output else "(无输出)"

    except subprocess.TimeoutExpired:
        return "错误: 命令超时 (60s)"
    except Exception as e:
        return f"错误: {e}"


def run_read_file(path: str, limit: int = None) -> str:
    """Read file contents with optional line limit.

    Features:
    - Safe path resolution
    - Optional line limit for large files
    - Output truncated to 50KB
    """
    try:
        text = safe_path(path).read_text()
        lines = text.splitlines()

        if limit and limit < len(lines):
            lines = lines[:limit]
            lines.append(f"... (还有 {len(text.splitlines()) - limit} 行)")

        return "\n".join(lines)[:50000]

    except Exception as e:
        return f"错误: {e}"


def run_write_file(path: str, content: str) -> str:
    """Write content to file, creating parent directories if needed.

    Features:
    - Safe path resolution
    - Auto-creates parent directories
    - Returns byte count for confirmation
    """
    try:
        fp = safe_path(path)
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content)
        return f"写入了 {len(content)} 字节到 {path}"

    except Exception as e:
        return f"错误: {e}"


def run_edit_file(path: str, old_text: str, new_text: str) -> str:
    """Replace exact text in a file (surgical edit).

    Features:
    - Exact string matching (not regex)
    - Only replaces first occurrence (safety)
    - Clear error if text not found
    """
    try:
        fp = safe_path(path)
        content = fp.read_text()

        if old_text not in content:
            return f"错误: 在 {path} 中未找到文本"

        new_content = content.replace(old_text, new_text, 1)
        fp.write_text(new_content)
        return f"已编辑 {path}"

    except Exception as e:
        return f"错误: {e}"


# =============================================================================
# 调度模式
# =============================================================================

def execute_tool(name: str, args: dict) -> str:
    """Dispatch tool call to implementation.

    This pattern makes it easy to add new tools:
    1. Add definition to TOOLS list
    2. Add implementation function
    3. Add case to this dispatcher
    """
    if name == "bash":
        return run_bash(args["command"])
    if name == "read_file":
        return run_read_file(args["path"], args.get("limit"))
    if name == "write_file":
        return run_write_file(args["path"], args["content"])
    if name == "edit_file":
        return run_edit_file(args["path"], args["old_text"], args["new_text"])
    # Add more tools here...
    return f"未知工具: {name}"
