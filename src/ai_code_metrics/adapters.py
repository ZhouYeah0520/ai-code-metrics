from __future__ import annotations

import json
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass
class AgentResult:
    tool: str
    output: str
    error: str
    exit_code: int
    duration_ms: int

    @property
    def ok(self) -> bool:
        return self.exit_code == 0


def normalize_exit_code(exit_code: int, output: str, error: str) -> int:
    """Treat provider/CLI errors on stderr as failures even when a wrapper exits 0."""
    if exit_code != 0:
        return exit_code
    diagnostic = f"{output}\n{error}".lower()
    error_markers = (
        "unrecognized_model", "authentication_error", "not authenticated",
        "authentication required", "invalid api key", "permission denied",
        "rate limit exceeded", "api error",
    )
    return 1 if any(marker in diagnostic for marker in error_markers) else 0


def parse_claude_output(raw: str) -> str:
    try:
        payload = json.loads(raw)
        if isinstance(payload, dict):
            return str(payload.get("result") or payload.get("content") or raw)
    except json.JSONDecodeError:
        pass
    return raw.strip()


def parse_codex_output(raw: str) -> str:
    texts = []
    for line in raw.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        if event.get("type") == "item.completed":
            item = event.get("item", {})
            if isinstance(item, dict) and item.get("type") == "agent_message":
                texts.append(str(item.get("text", "")))
        elif event.get("type") == "message" and isinstance(event.get("content"), str):
            texts.append(event["content"])
    return "\n".join(texts).strip() or raw.strip()


def run_agent(tool: str, prompt: str, cwd: str | Path = ".", timeout: int = 120, edit: bool = False) -> AgentResult:
    if tool == "claude-code":
        executable = shutil.which("claude")
        command = []
        if executable:
            command = [executable, "-p", prompt]
            if edit:
                # 只允许文件读写，避免自动修复阶段获得任意命令执行权限。
                command += ["--allowedTools", "Read,Edit,Write", "--permission-mode", "acceptEdits"]
            command += ["--output-format", "json"]
        parser = parse_claude_output
    elif tool == "codex":
        executable = shutil.which("codex")
        command = []
        if executable:
            # 适配器可用于尚未初始化 Git 的源码目录；Codex 默认会拒绝此类目录。
            command = [executable, "exec", "--json", "--skip-git-repo-check"]
            if edit:
                # `--full-auto` 已从当前 Codex CLI 移除；workspace-write 允许编辑，
                # skip-git-repo-check 支持在仅包含源码的临时目录运行闭环。
                command += ["--sandbox", "workspace-write"]
            command += [prompt]
        parser = parse_codex_output
    else:
        raise ValueError(f"Unsupported tool: {tool}")
    if not command:
        return AgentResult(tool, "", f"{tool} CLI not found on PATH", 127, 0)
    started = time.monotonic()
    try:
        proc = subprocess.run(
            command, cwd=Path(cwd).resolve(), text=True, encoding="utf-8",
            errors="replace", capture_output=True, timeout=timeout, check=False,
        )
        output = parser(proc.stdout)
        error = proc.stderr.strip()
        return AgentResult(tool, output, error, normalize_exit_code(proc.returncode, output, error),
                           round((time.monotonic() - started) * 1000))
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout.decode(errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        stderr = exc.stderr.decode(errors="replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        return AgentResult(tool, parser(stdout), stderr + f"\nTimed out after {timeout}s", 124,
                           round((time.monotonic() - started) * 1000))
