"""Subagent Pattern - 如何实现 Task 工具以进行上下文隔离。

核心洞察: 衍生具有隔离上下文的子代理，以防止"上下文污染"，即探索细节填满主对话。
"""

import sys
import time

# Assuming client, MODEL, execute_tool are defined elsewhere


# =============================================================================
# 代理类型注册表
# =============================================================================

AGENT_TYPES = {
    # Explore: Read-only, for searching and analyzing
    "explore": {
        "description": "只读代理，用于探索代码、查找文件、搜索",
        "tools": ["bash", "read_file"],  # No write access!
        "prompt": "你是一个探索代理。搜索和分析，但绝不要修改文件。返回你发现内容的简明摘要。",
    },

    # Code: Full-powered, for implementation
    "code": {
        "description": "全能代理，用于实现功能和修复错误",
        "tools": "*",  # All tools
        "prompt": "你是一个编码代理。高效地实现请求的更改。返回你更改内容的摘要。",
    },

    # Plan: Read-only, for design work
    "plan": {
        "description": "规划代理，用于设计实施策略",
        "tools": ["bash", "read_file"],  # Read-only
        "prompt": "你是一个规划代理。分析代码库并输出编号的实施计划。不要做任何更改。",
    },

    # Add your own types here...
    # "test": {
    #     "description": "测试代理，用于运行和分析测试",
    #     "tools": ["bash", "read_file"],
    #     "prompt": "运行测试并报告结果。不要修改代码。",
    # },
}


def get_agent_descriptions() -> str:
    """Generate descriptions for Task tool schema."""
    return "\n".join(
        f"- {name}: {cfg['description']}"
        for name, cfg in AGENT_TYPES.items()
    )


def get_tools_for_agent(agent_type: str, base_tools: list) -> list:
    """Filter tools based on agent type.

    '*' means all base tools.
    Otherwise, whitelist specific tool names.

    Note: Subagents don't get Task tool to prevent infinite recursion.
    """
    allowed = AGENT_TYPES.get(agent_type, {}).get("tools", "*")

    if allowed == "*":
        return base_tools  # All base tools, but NOT Task

    return [t for t in base_tools if t["name"] in allowed]


# =============================================================================
# 任务工具定义
# =============================================================================

TASK_TOOL = {
    "name": "Task",
    "description": f"""衍生一个子代理来处理专注的子任务。

子代理在隔离的上下文中运行 - 它们看不到父代理的历史记录。
使用此功能保持主对话整洁。

代理类型:
{get_agent_descriptions()}

使用示例:
- Task(explore): "查找所有使用 auth 模块的文件"
- Task(plan): "为数据库设计迁移策略"
- Task(code): "实现用户注册表单"
""",
    "input_schema": {
        "type": "object",
        "properties": {
            "description": {
                "type": "string",
                "description": "用于进度显示的简短任务名称 (3-5 个词)",
            },
            "prompt": {
                "type": "string",
                "description": "子代理的详细说明",
            },
            "agent_type": {
                "type": "string",
                "enum": list(AGENT_TYPES.keys()),
                "description": "要衍生的代理类型",
            },
        },
        "required": ["description", "prompt", "agent_type"],
    },
}


# =============================================================================
# 子代理执行
# =============================================================================

def run_task(description: str, prompt: str, agent_type: str,
             client, model: str, workdir, base_tools: list, execute_tool) -> str:
    """Execute a subagent task with isolated context.

    Key concepts:
    1. ISOLATED HISTORY - subagent starts fresh, no parent context
    2. FILTERED TOOLS - based on agent type permissions
    3. AGENT-SPECIFIC PROMPT - specialized behavior
    4. RETURNS SUMMARY ONLY - parent sees just the final result

    Args:
        description: Short name for progress display
        prompt: Detailed instructions for subagent
        agent_type: Key from AGENT_TYPES
        client: Anthropic client
        model: Model to use
        workdir: Working directory
        base_tools: List of tool definitions
        execute_tool: Function to execute tools

    Returns:
        Final text output from subagent

    """
    if agent_type not in AGENT_TYPES:
        return f"错误: 未知代理类型 '{agent_type}'"

    config = AGENT_TYPES[agent_type]

    # Agent-specific system prompt
    sub_system = f"""你是一个 {agent_type} 子代理，位于 {workdir}。

{config["prompt"]}

完成任务并返回清晰、简明的摘要。"""

    # Filtered tools for this agent type
    sub_tools = get_tools_for_agent(agent_type, base_tools)

    # KEY: ISOLATED message history!
    # The subagent starts fresh, doesn't see parent's conversation
    sub_messages = [{"role": "user", "content": prompt}]

    # Progress display
    print(f"  [{agent_type}] {description}")
    start = time.time()
    tool_count = 0

    # Run the same agent loop (but silently)
    while True:
        response = client.messages.create(
            model=model,
            system=sub_system,
            messages=sub_messages,
            tools=sub_tools,
            max_tokens=8000,
        )

        # Check if done
        if response.stop_reason != "tool_use":
            break

        # Execute tools
        tool_calls = [b for b in response.content if b.type == "tool_use"]
        results = []

        for tc in tool_calls:
            tool_count += 1
            output = execute_tool(tc.name, tc.input)
            results.append({
                "type": "tool_result",
                "tool_use_id": tc.id,
                "content": output,
            })

            # Update progress (in-place on same line)
            elapsed = time.time() - start
            sys.stdout.write(
                f"\r  [{agent_type}] {description} ... {tool_count} 个工具, {elapsed:.1f}s",
            )
            sys.stdout.flush()

        sub_messages.append({"role": "assistant", "content": response.content})
        sub_messages.append({"role": "user", "content": results})

    # Final progress update
    elapsed = time.time() - start
    sys.stdout.write(
        f"\r  [{agent_type}] {description} - 完成 ({tool_count} 个工具, {elapsed:.1f}s)\n",
    )

    # Extract and return ONLY the final text
    # This is what the parent agent sees - a clean summary
    for block in response.content:
        if hasattr(block, "text"):
            return block.text

    return "(子代理未返回文本)"


# =============================================================================
# USAGE EXAMPLE
# =============================================================================

"""
# In your main agent's execute_tool function:

def execute_tool(name: str, args: dict) -> str:
    if name == "Task":
        return run_task(
            description=args["description"],
            prompt=args["prompt"],
            agent_type=args["agent_type"],
            client=client,
            model=MODEL,
            workdir=WORKDIR,
            base_tools=BASE_TOOLS,
            execute_tool=execute_tool  # Pass self for recursion
        )
    # ... other tools ...


# In your TOOLS list:
TOOLS = BASE_TOOLS + [TASK_TOOL]
"""
