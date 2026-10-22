from __future__ import annotations

import json
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

NOTES_REF = "refs/notes/ai-code-metrics"


class GitError(RuntimeError):
    pass


def git(args: list[str], cwd: str | Path | None = None, *, check: bool = True) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=cwd, text=True, encoding="utf-8",
        errors="replace", capture_output=True, check=False,
    )
    if check and proc.returncode:
        raise GitError(proc.stderr.strip() or f"git {' '.join(args)} failed")
    return proc.stdout.strip()


@dataclass(frozen=True)
class ChangeCount:
    files: int = 0
    added: int = 0
    deleted: int = 0


def commit_changes(commit: str, cwd: str | Path | None = None) -> ChangeCount:
    """Count text changes against the first parent (or the empty tree)."""
    parents = git(["rev-list", "--parents", "-n", "1", commit], cwd).split()
    if not parents:
        raise GitError(f"Cannot resolve commit: {commit}")
    base = parents[1] if len(parents) > 1 else git(["hash-object", "-t", "tree", "--stdin"], cwd)
    raw = subprocess.run(
        ["git", "diff", "--numstat", base, parents[0]], cwd=cwd,
        text=True, encoding="utf-8", errors="replace", capture_output=True, check=False,
    )
    if raw.returncode:
        raise GitError(raw.stderr.strip() or f"Unable to count changes for {commit}")
    files = added = deleted = 0
    for line in raw.stdout.splitlines():
        fields = line.split("\t", 2)
        if len(fields) != 3:
            continue
        files += 1
        if fields[0].isdigit():
            added += int(fields[0])
        if fields[1].isdigit():
            deleted += int(fields[1])
    return ChangeCount(files, added, deleted)


def commits_between(since: str | None, until: str = "HEAD", cwd: str | Path | None = None) -> list[str]:
    revision = f"{since}..{until}" if since else until
    output = git(["rev-list", "--reverse", "--no-merges", revision], cwd)
    return output.splitlines() if output else []


def add_ai_note(commit: str, tool: str, cwd: str | Path | None = None) -> dict:
    resolved = git(["rev-parse", "--verify", f"{commit}^{{commit}}"], cwd)
    changes = commit_changes(resolved, cwd)
    payload = {
        "schema_version": 1,
        "tool": tool,
        "files": changes.files,
        "added": changes.added,
        "deleted": changes.deleted,
    }
    git(["notes", f"--ref={NOTES_REF}", "add", "-f", "-m", json.dumps(payload), resolved], cwd)
    return {"commit": resolved, **payload}


def read_ai_note(commit: str, cwd: str | Path | None = None) -> dict | None:
    result = subprocess.run(
        ["git", "notes", f"--ref={NOTES_REF}", "show", commit], cwd=cwd,
        text=True, encoding="utf-8", errors="replace", capture_output=True, check=False,
    )
    if result.returncode:
        return None
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError:
        return {"tool": "legacy", "added": None, "deleted": None, "files": None}
    return value if isinstance(value, dict) else None


def ratio(since: str | None, until: str = "HEAD", cwd: str | Path | None = None) -> dict:
    commits = commits_between(since, until, cwd)
    total_added = ai_added = ai_commits = 0
    for commit in commits:
        count = commit_changes(commit, cwd)
        total_added += count.added
        if read_ai_note(commit, cwd) is not None:
            ai_commits += 1
            ai_added += count.added
    return {
        "since": since,
        "until": until,
        "commits": len(commits),
        "ai_commits": ai_commits,
        "total_added": total_added,
        "ai_added": ai_added,
        "ratio": round(ai_added / total_added, 4) if total_added else None,
        "unit": "added_lines",
    }


def list_marked(since: str | None, until: str = "HEAD", cwd: str | Path | None = None) -> list[dict]:
    result = []
    for commit in commits_between(since, until, cwd):
        note = read_ai_note(commit, cwd)
        if note is not None:
            result.append({"commit": commit, **note})
    return result
