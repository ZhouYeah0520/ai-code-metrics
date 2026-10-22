from __future__ import annotations

import subprocess
from pathlib import Path

from .adapters import run_agent


def run_tests(test_cmd: list[str], cwd: Path) -> tuple[bool, str]:
    """Run a test command; return (passed, combined output)."""
    proc = subprocess.run(
        test_cmd, cwd=cwd, text=True, encoding="utf-8", errors="replace",
        capture_output=True, check=False,
    )
    return proc.returncode == 0, (proc.stdout + proc.stderr).strip()


def auto_fix(tool: str, test_cmd: list[str], cwd: str | Path = ".",
             rounds: int = 5, timeout: int = 300) -> dict:
    """ReAct 风格的最小闭环：跑测试 → 让 Agent 修改 → 再跑，最多 rounds 轮。

    每一步都把最新失败输出喂回所选 CLI，让它据此迭代修复；CLI 调用失败
    时立即停止并返回错误，避免空转。
    """
    cwd = Path(cwd).resolve()
    passed, output = run_tests(test_cmd, cwd)
    if passed:
        return {"rounds": 0, "fixed": True, "final_output": output}

    for i in range(1, rounds + 1):
        prompt = (
            "下面的测试失败了，请定位并修改代码，使测试通过。\n\n"
            f"{output[-8000:]}\n\n"
            "请直接修改文件；不要运行测试，我会在下一步验证。"
        )
        result = run_agent(tool, prompt, cwd, timeout=timeout, edit=True)
        if not result.ok:
            return {"rounds": i, "fixed": False, "final_output": output,
                    "agent_error": result.error}
        passed, output = run_tests(test_cmd, cwd)
        if passed:
            return {"rounds": i, "fixed": True, "final_output": output}

    return {"rounds": rounds, "fixed": False, "final_output": output}
