"""
沙箱安全执行引擎（终极稳定版）
使用 subprocess + 临时文件替代 multiprocessing，彻底解决 Windows 死锁和报错问题
"""
import re
import sys
import os
import ast
import subprocess
import tempfile
from dataclasses import dataclass
from typing import Optional, Dict, Any


@dataclass
class ExecutionResult:
    success: bool
    output: str
    error: Optional[str] = None


# 禁止用户代码 import 的模块
BANNED_MODULES = {
    "subprocess", "ctypes", "socket", "http",
    "urllib", "requests", "ftplib", "smtplib", "pickle",
    "shutil", "tempfile", "multiprocessing", "threading",
    "asyncio", "webbrowser", "tkinter"
}

# 禁止 os 模块中的危险函数（os 模块本身可用，但这些操作不行）
BANNED_OS_FUNCS = {
    "remove", "system", "popen", "unlink", "rmdir", "removedirs",
    "chdir", "chmod", "kill", "rename", "replace"
}

# 禁止调用的函数
BANNED_BUILTINS = {"exec", "eval", "compile", "__import__", "input"}


def _static_check(code: str) -> Optional[str]:
    """AST 静态安全检查：禁止 import 危险模块 + 禁止 os 的危险函数"""
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return f"代码语法错误: {e}"

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] in BANNED_MODULES:
                    return f"禁止导入模块: {alias.name}"
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.module.split(".")[0] in BANNED_MODULES:
                return f"禁止导入模块: {node.module}"
        elif isinstance(node, ast.Call):
            # 检查危险内置函数
            if isinstance(node.func, ast.Name) and node.func.id in BANNED_BUILTINS:
                return f"禁止使用危险函数: {node.func.id}"
            # 检查 os.危险函数() 调用（如 os.remove, os.system）
            if isinstance(node.func, ast.Attribute):
                if isinstance(node.func.value, ast.Name) and node.func.value.id == "os":
                    if node.func.attr in BANNED_OS_FUNCS:
                        return f"禁止使用 os.{node.func.attr}()"
            # ===== 修复7新增：拦截 open() 读取敏感文件 =====
            if isinstance(node.func, ast.Name) and node.func.id == "open" and node.args:
                first = node.args[0]
                if isinstance(first, ast.Constant) and isinstance(first.value, str):
                    for banned_name in (".env", "checkpoint", "config.py"):
                        if banned_name in first.value.lower():
                            return f"禁止读取敏感文件: {first.value}"

    return None


def execute_in_sandbox(
    code: str, 
    sandbox_globals: Optional[Dict[str, Any]] = None, 
    timeout: int = 30
) -> ExecutionResult:
    """
    使用 subprocess 在新进程中执行代码，带超时控制。
    彻底避免 multiprocessing 的死锁和 Windows 兼容性问题。
    """
    if sandbox_globals is None:
        sandbox_globals = {}

    # 1. 静态安全检查
    check_result = _static_check(code)
    if check_result:
        return ExecutionResult(success=False, output="", error=check_result)

    # 2. 准备全局变量注入代码（如 df, pd, plt 等）
    # 把 sandbox_globals 中的变量序列化为代码注入到临时文件顶部
    globals_inject_code = ""
    for name, value in sandbox_globals.items():
        if name.startswith('_'):
            continue
        # 简单安全地序列化基本类型和 pandas DataFrame
        if hasattr(value, '__class__') and 'DataFrame' in value.__class__.__name__:
            # 如果是 DataFrame，假设外部已经把它作为全局变量准备好，或者在这里用 to_csv/read_csv 传递
            # 最简单的方案：让调用方在 code 顶部自己 import 和加载 df
            pass
        else:
            try:
                globals_inject_code += f"{name} = {repr(value)}\n"
            except Exception:
                pass

    # 3. 组装最终要在沙箱中运行的完整代码
    # ⚠️ 不能用 f-string 拼接，否则 LLM 生成的代码里如果有 {xxx} 花括号会被外层 f-string 错误求值 → NameError！
    # 用安全占位符替换，确保 LLM 代码里的任何花括号都不会干扰拼接
    _TEMPLATE = """
__SANDBOX_GLOBALS__
# 用户代码开始
__SANDBOX_USER_CODE__

# ========== 自动提取 result 变量（多重兜底）==========
import sys as _sys
_result_val = None
try:
    # 策略 1：直接从全局命名空间（模块顶层）读取
    if 'result' in globals():
        _result_val = globals()['result']
    # 策略 2：从 __main__ 模块读取
    if _result_val is None:
        _m = _sys.modules.get('__main__')
        if _m is not None and hasattr(_m, 'result'):
            _result_val = _m.result
    # 策略 3：直接裸读取（exec 作用域下）
    if _result_val is None:
        try:
            _result_val = result  # noqa: F821
        except NameError:
            pass
    # 用明显的标记行输出，便于 executor_node 精准提取
    if _result_val is not None:
        print("__RESULT_START__")
        print(str(_result_val))
        print("__RESULT_END__")
    else:
        print("__RESULT_START__")
        print("(result 变量未设置，请检查代码是否将分析结论赋值给了 result)")
        print("__RESULT_END__")
except Exception as _e:
    print("__RESULT_START__")
    print(f"result 提取失败: {type(_e).__name__}: {_e}")
    print("__RESULT_END__")
"""
    full_code = _TEMPLATE.replace("__SANDBOX_GLOBALS__", globals_inject_code) \
                        .replace("__SANDBOX_USER_CODE__", code)

    # 4. 创建临时文件
    try:
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False, encoding='utf-8') as f:
            f.write(full_code)
            temp_path = f.name
    except Exception as e:
        return ExecutionResult(success=False, output="", error=f"创建临时文件失败: {e}")

    # 5. 使用 subprocess 执行临时文件
    try:
        _env = os.environ.copy()
        _env['PYTHONIOENCODING'] = 'utf-8'
        result = subprocess.run(
            [sys.executable, temp_path],
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=timeout,
            cwd=os.getcwd(),  # 确保工作目录一致，方便读写 data/ 目录
            env=_env,
        )
        
        # 防御性兜底：Windows 上某些边界情况会导致 stdout/stderr 为 None
        output = (result.stdout or "").strip()
        stderr_text = (result.stderr or "").strip()

        # 关键修复：success 只看 returncode！
        # matplotlib/pandas/numpy 等库的 WARNING 会输出到 stderr（如 findfont 警告），
        # 但只要 returncode == 0 进程就正常退出了，这些只是噪音不是错误。
        # 只有当 returncode != 0（真正崩溃）才把 stderr 当错误信息。
        if result.returncode == 0:
            # 如果 stderr 有 WARNING，拼到 output 里当日志信息，但不影响 success
            if stderr_text:
                output = output + "\n--- 运行日志 ---\n" + stderr_text
            return ExecutionResult(success=True, output=output)
        else:
            err_msg = stderr_text if stderr_text else f"代码执行失败，返回码: {result.returncode}"
            return ExecutionResult(success=False, output=output, error=err_msg)

    except subprocess.TimeoutExpired:
        return ExecutionResult(
            success=False,
            output="",
            error=f"代码执行超时（超过 {timeout} 秒），可能包含无限循环。"
        )
    except Exception as e:
        return ExecutionResult(success=False, output="", error=f"执行过程发生异常: {str(e)}")
    finally:
        # 6. 清理临时文件
        try:
            os.unlink(temp_path)
        except Exception:
            pass