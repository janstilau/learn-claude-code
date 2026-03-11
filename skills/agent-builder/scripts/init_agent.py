#!/usr/bin/env python3
"""Agent Scaffold Script - 创建具有最佳实践的新代理项目。

用法:
    python init_agent.py <agent-name> [--level 0-4] [--path <output-dir>]

示例:
    python init_agent.py my-agent                 # Level 1 (4 个工具)
    python init_agent.py my-agent --level 0      # 极简 (仅 bash)
    python init_agent.py my-agent --level 2      # 带 TodoWrite
    python init_agent.py my-agent --path ./bots  # 自定义输出目录
"""

import argparse
import sys
from pathlib import Path

# Agent templates for each level
TEMPLATES = {
    0: '''#!/usr/bin/env python3
"""
Level 0 Agent - Bash 就是你所需的一切 (~50 行)

核心洞察: 一个工具 (bash) 可以做任何事。
通过自递归实现子代理: python {name}.py "subtask"
"""

from anthropic import Anthropic
from dotenv import load_dotenv
import subprocess
import os

load_dotenv()

client = Anthropic(
    api_key=os.getenv("ANTHROPIC_API_KEY"),
    base_url=os.getenv("ANTHROPIC_BASE_URL")
)
MODEL = os.getenv("MODEL_NAME", "claude-sonnet-4-20250514")

SYSTEM = """你是一个编码代理。对所有事情都使用 bash:
- 读取: cat, grep, find, ls
- 写入: echo 'content' > file
- 子代理: python {name}.py "subtask"
"""

TOOL = [{{
    "name": "bash",
    "description": "执行 shell 命令",
    "input_schema": {{"type": "object", "properties": {{"command": {{"type": "string"}}}}, "required": ["command"]}}
}}]

def run(prompt, history=[]):
    history.append({{"role": "user", "content": prompt}})
    while True:
        r = client.messages.create(model=MODEL, system=SYSTEM, messages=history, tools=TOOL, max_tokens=8000)
        history.append({{"role": "assistant", "content": r.content}})
        if r.stop_reason != "tool_use":
            return "".join(b.text for b in r.content if hasattr(b, "text"))
        results = []
        for b in r.content:
            if b.type == "tool_use":
                print(f"> {{b.input['command']}}")
                try:
                    out = subprocess.run(b.input["command"], shell=True, capture_output=True, text=True, timeout=60)
                    output = (out.stdout + out.stderr).strip() or "(无输出)"
                except Exception as e:
                    output = f"错误: {{e}}"
                results.append({{"type": "tool_result", "tool_use_id": b.id, "content": output[:50000]}})
        history.append({{"role": "user", "content": results}})

if __name__ == "__main__":
    h = []
    print("{name} - Level 0 Agent\\n输入 'q' 退出。\\n")
    while (q := input(">> ").strip()) not in ("q", "quit", ""):
        print(run(q, h), "\\n")
''',

    1: '''#!/usr/bin/env python3
"""
Level 1 Agent - 模型即代理 (~200 行)

核心洞察: 4 个工具覆盖 90% 的编码任务。
模型就是代理。代码只是运行循环。
"""

from anthropic import Anthropic
from dotenv import load_dotenv
from pathlib import Path
import subprocess
import os

load_dotenv()

client = Anthropic(
    api_key=os.getenv("ANTHROPIC_API_KEY"),
    base_url=os.getenv("ANTHROPIC_BASE_URL")
)
MODEL = os.getenv("MODEL_NAME", "claude-sonnet-4-20250514")
WORKDIR = Path.cwd()

SYSTEM = f"""你是位于 {{WORKDIR}} 的编码代理。

规则:
- 优先使用工具而不是文字。行动，不要只是解释。
- 永远不要编造文件路径。如果不确定，先使用 ls/find。
- 做最小的改动。不要过度设计。
- 完成后，总结变更内容。"""

TOOLS = [
    {{"name": "bash", "description": "运行 shell 命令",
     "input_schema": {{"type": "object", "properties": {{"command": {{"type": "string"}}}}, "required": ["command"]}}}},
    {{"name": "read_file", "description": "读取文件内容",
     "input_schema": {{"type": "object", "properties": {{"path": {{"type": "string"}}}}, "required": ["path"]}}}},
    {{"name": "write_file", "description": "将内容写入文件",
     "input_schema": {{"type": "object", "properties": {{"path": {{"type": "string"}}, "content": {{"type": "string"}}}}, "required": ["path", "content"]}}}},
    {{"name": "edit_file", "description": "替换文件中的确切文本",
     "input_schema": {{"type": "object", "properties": {{"path": {{"type": "string"}}, "old_text": {{"type": "string"}}, "new_text": {{"type": "string"}}}}, "required": ["path", "old_text", "new_text"]}}}},
]

def safe_path(p: str) -> Path:
    """防止路径逃逸攻击。"""
    path = (WORKDIR / p).resolve()
    if not path.is_relative_to(WORKDIR):
        raise ValueError(f"路径超出工作区范围: {{p}}")
    return path

def execute(name: str, args: dict) -> str:
    """执行工具并返回结果。"""
    if name == "bash":
        dangerous = ["rm -rf /", "sudo", "shutdown", "> /dev/"]
        if any(d in args["command"] for d in dangerous):
            return "错误: 危险命令已阻止"
        try:
            r = subprocess.run(args["command"], shell=True, cwd=WORKDIR, capture_output=True, text=True, timeout=60)
            return (r.stdout + r.stderr).strip()[:50000] or "(无输出)"
        except subprocess.TimeoutExpired:
            return "错误: 超时 (60s)"
        except Exception as e:
            return f"错误: {{e}}"

    if name == "read_file":
        try:
            return safe_path(args["path"]).read_text()[:50000]
        except Exception as e:
            return f"错误: {{e}}"

    if name == "write_file":
        try:
            p = safe_path(args["path"])
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(args["content"])
            return f"写入了 {{len(args['content'])}} 字节到 {{args['path']}}"
        except Exception as e:
            return f"错误: {{e}}"

    if name == "edit_file":
        try:
            p = safe_path(args["path"])
            content = p.read_text()
            if args["old_text"] not in content:
                return f"错误: 在 {{args['path']}} 中未找到文本"
            p.write_text(content.replace(args["old_text"], args["new_text"], 1))
            return f"已编辑 {{args['path']}}"
        except Exception as e:
            return f"错误: {{e}}"

    return f"未知工具: {{name}}"

def agent(prompt: str, history: list = None) -> str:
    """运行代理循环。"""
    if history is None:
        history = []
    history.append({{"role": "user", "content": prompt}})

    while True:
        response = client.messages.create(
            model=MODEL, system=SYSTEM, messages=history, tools=TOOLS, max_tokens=8000
        )
        history.append({{"role": "assistant", "content": response.content}})

        if response.stop_reason != "tool_use":
            return "".join(b.text for b in response.content if hasattr(b, "text"))

        results = []
        for block in response.content:
            if block.type == "tool_use":
                print(f"> {{block.name}}: {{str(block.input)[:100]}}")
                output = execute(block.name, block.input)
                print(f"  {{output[:100]}}...")
                results.append({{"type": "tool_result", "tool_use_id": block.id, "content": output}})
        history.append({{"role": "user", "content": results}})

if __name__ == "__main__":
    print(f"{name} - Level 1 Agent at {{WORKDIR}}")
    print("输入 'q' 退出。\\n")
    h = []
    while True:
        try:
            query = input(">> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if query in ("q", "quit", "exit", ""):
            break
        print(agent(query, h), "\\n")
''',
}

ENV_TEMPLATE = """# API 配置
ANTHROPIC_API_KEY=sk-xxx
ANTHROPIC_BASE_URL=https://api.anthropic.com
MODEL_NAME=claude-sonnet-4-20250514
"""


def create_agent(name: str, level: int, output_dir: Path):
    """创建新的代理项目。"""
    # Validate level
    if level not in TEMPLATES and level not in (2, 3, 4):
        print(f"错误: Level {level} 尚未在脚手架中实现。")
        print("可用级别: 0 (极简), 1 (4 个工具)")
        print("对于级别 2-4，请从 mini-claude-code 仓库复制。")
        sys.exit(1)

    # Create output directory
    agent_dir = output_dir / name
    agent_dir.mkdir(parents=True, exist_ok=True)

    # Write agent file
    agent_file = agent_dir / f"{name}.py"
    template = TEMPLATES.get(level, TEMPLATES[1])
    agent_file.write_text(template.format(name=name))
    print(f"已创建: {agent_file}")

    # Write .env.example
    env_file = agent_dir / ".env.example"
    env_file.write_text(ENV_TEMPLATE)
    print(f"已创建: {env_file}")

    # Write .gitignore
    gitignore = agent_dir / ".gitignore"
    gitignore.write_text(".env\n__pycache__/\n*.pyc\n")
    print(f"已创建: {gitignore}")

    print(f"\n代理 '{name}' 已创建于 {agent_dir}")
    print("\n下一步:")
    print(f"  1. cd {agent_dir}")
    print("  2. cp .env.example .env")
    print("  3. 编辑 .env 填入你的 API key")
    print("  4. pip install anthropic python-dotenv")
    print(f"  5. python {name}.py")


def main():
    parser = argparse.ArgumentParser(
        description="搭建一个新的 AI 编码代理项目",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
级别:
  0  极简 (~50 行)   - 单个 bash 工具，通过自递归实现子代理
  1  基础 (~200 行)  - 4 个核心工具: bash, read, write, edit
  2  待办 (~300 行)  - + TodoWrite 用于结构化规划
  3  子代理 (~450)   - + Task 工具用于上下文隔离
  4  技能 (~550)     - + Skill 工具用于领域专业知识
        """,
    )
    parser.add_argument("name", help="要创建的代理名称")
    parser.add_argument("--level", type=int, default=1, choices=[0, 1, 2, 3, 4],
                       help="复杂度级别 (默认: 1)")
    parser.add_argument("--path", type=Path, default=Path.cwd(),
                       help="输出目录 (默认: 当前目录)")

    args = parser.parse_args()
    create_agent(args.name, args.level, args.path)


if __name__ == "__main__":
    main()
