#!/usr/bin/env python3
"""
logtool.py - 通用日志和彩色打印工具

提供统一的日志记录功能（JSONL 格式）和标准化的控制台彩色输出。
"""

import os
import json
import time
from datetime import datetime

# ANSI 颜色代码
class Colors:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    
    # 前景色
    BLACK = "\033[30m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    WHITE = "\033[37m"
    ORANGE = "\033[38;5;208m"  # 扩展颜色代码
    GRAY = "\033[90m"

class Logger:
    def __init__(self, log_dir="logs"):
        self.log_dir = os.path.join(os.getcwd(), log_dir)
        os.makedirs(self.log_dir, exist_ok=True)
        self.session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.log_file = os.path.join(self.log_dir, f"agent_trace_{self.session_id}.jsonl")
        print(f"{Colors.GRAY}Logging trace to: {self.log_file}{Colors.RESET}")

    def log_interaction(self, request_data: dict, response_data: dict):
        """记录一次完整的交互（Request + Response）"""
        interaction_log = {
            "timestamp": datetime.now().isoformat(),
            "type": "interaction",
            "request": request_data,
            "response": response_data
        }
        
        with open(self.log_file, "a", encoding="utf-8") as f:
            # 使用 indent=2 方便人类阅读，并在记录间添加逗号和换行
            f.write(json.dumps(interaction_log, ensure_ascii=False, indent=2) + "\n,\n")

# 全局单例
_logger = None

def get_logger():
    global _logger
    if _logger is None:
        _logger = Logger()
    return _logger

def print_user(text: str):
    """打印用户输入提示符或内容 (Cyan)"""
    print(f"{Colors.CYAN}{text}{Colors.RESET}")

def print_model_response_header():
    """打印模型响应头 (Bold)"""
    print(f"\n{Colors.BOLD}--- model_response ---{Colors.RESET}")

def print_model_text(text: str):
    """打印模型文本回复 (Orange)"""
    print(f"{Colors.ORANGE}{text}{Colors.RESET}")

def print_tool_use(tool_input: dict):
    """打印工具调用信息 (Yellow)"""
    print(f"{Colors.YELLOW}Tool Use: {tool_input}{Colors.RESET}")

def print_tool_result(result: str):
    """打印工具执行结果 (Green)"""
    # 截断过长的输出
    display_text = result[:500] + ("..." if len(result) > 500 else "")
    print(f"{Colors.GREEN}Tool Result: {display_text}{Colors.RESET}")

def print_error(text: str):
    """打印错误信息 (Red)"""
    print(f"{Colors.RED}{text}{Colors.RESET}")

def print_info(text: str):
    """打印一般信息 (Gray)"""
    print(f"{Colors.GRAY}{text}{Colors.RESET}")
