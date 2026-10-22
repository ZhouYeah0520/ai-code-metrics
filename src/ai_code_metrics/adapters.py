from __future__ import annotations

import json
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from typing import Callable
from pathlib import Path


@dataclass(frozen=True)
class AgentAdapter:
    """One normalized interface for an external coding-agent CLI."""

    tool: str
    executable_name: str
    parser: Callable[[str], str]
    command_builder: Callable[[str, str, bool], list[str]]

    def build_command(self, executable: str, prompt: str, edit: bool) -> list[str]:
        return self.command_builder(executable, prompt, edit)


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
    diagnostic = re.sub(r"[^a-z0-9]+", "_", f"{output}\n{error}".lower()).strip("_")
    error_markers = (
        "unrecognized_model", "authentication_error", "not_authenticated",
        "authentication_required", "invalid_api_key", "permission_denied",
        "rate_limit_exceeded", "api_error",
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


def _build_claude_command(executable: str, prompt: str, edit: bool) -> list[str]:
    command = [executable, "-p", prompt]
    if edit:
        command += ["--allowedTools", "Read,Edit,Write", "--permission-mode", "acceptEdits"]
    return command + ["--output-format", "json"]


def _build_codex_command(executable: str, prompt: str, edit: bool) -> list[str]:
    command = [executable, "exec", "--json", "--skip-git-repo-check"]
    if edit:
        command += ["--sandbox", "workspace-write"]
    return command + [prompt]


_ADAPTERS = {
    "claude-code": AgentAdapter(
        "claude-code", "claude", parse_claude_output, _build_claude_command,
    ),
    "codex": AgentAdapter(
        "codex", "codex", parse_codex_output, _build_codex_command,
    ),
}


def get_adapter(tool: str) -> AgentAdapter:
    try:
        return _ADAPTERS[tool]
    except KeyError as exc:
        raise ValueError(f"Unsupported tool: {tool}") from exc


def run_agent(tool: str, prompt: str, cwd: str | Path = ".", timeout: int = 120, edit: bool = False) -> AgentResult:
    adapter = get_adapter(tool)
    executable = shutil.which(adapter.executable_name)
    command = adapter.build_command(executable, prompt, edit) if executable else []
    if not command:
        return AgentResult(tool, "", f"{tool} CLI not found on PATH", 127, 0)
    started = time.monotonic()
    try:
        proc = subprocess.run(
            command, cwd=Path(cwd).resolve(), text=True, encoding="utf-8",
            errors="replace", capture_output=True, timeout=timeout, check=False,
        )
        output = adapter.parser(proc.stdout)
        error = proc.stderr.strip()
        return AgentResult(tool, output, error, normalize_exit_code(proc.returncode, output, error),
                           round((time.monotonic() - started) * 1000))
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout.decode(errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        stderr = exc.stderr.decode(errors="replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        return AgentResult(tool, adapter.parser(stdout), stderr + f"\nTimed out after {timeout}s", 124,
                           round((time.monotonic() - started) * 1000))
