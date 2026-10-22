from __future__ import annotations

import argparse
import json
import shlex
from pathlib import Path

from .adapters import run_agent
from .fix import auto_fix
from .git import GitError, add_ai_note, git, list_marked, ratio


def install_hook(cwd: str | Path = ".") -> Path:
    root = Path(git(["rev-parse", "--show-toplevel"], cwd=cwd)).resolve()
    hooks = Path(git(["rev-parse", "--git-path", "hooks"], cwd=root))
    if not hooks.is_absolute():
        hooks = (root / hooks).resolve()
    hooks.mkdir(parents=True, exist_ok=True)
    hook = hooks / "post-commit"
    hook.write_text(
        "#!/bin/sh\n"
        "repo_root=$(git rev-parse --show-toplevel) || exit 1\n"
        "message=$(git -C \"$repo_root\" log -1 --pretty=%B)\n"
        "case \"$message\" in\n"
        "  *\"[AI]\"*) python -m ai_code_metrics mark --cwd \"$repo_root\" --commit HEAD --tool hook >/dev/null || exit $? ;;\n"
        "esac\n",
        encoding="utf-8", newline="\n",
    )
    return hook


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ai-code-metrics")
    sub = parser.add_subparsers(dest="command", required=True)
    mark = sub.add_parser("mark", help="Mark a commit as AI-assisted")
    mark.add_argument("--commit", default="HEAD")
    mark.add_argument("--tool", default="manual")
    mark.add_argument("--cwd", default=".")
    metrics = sub.add_parser("ratio", help="Measure added-line share in a commit range")
    metrics.add_argument("--since", help="Exclusive starting revision")
    metrics.add_argument("--until", default="HEAD")
    metrics.add_argument("--cwd", default=".")
    listing = sub.add_parser("list", help="List marked commits in a range")
    listing.add_argument("--since")
    listing.add_argument("--until", default="HEAD")
    listing.add_argument("--cwd", default=".")
    agent = sub.add_parser("run", help="Run an installed coding assistant CLI")
    agent.add_argument("--tool", choices=["claude-code", "codex"], required=True)
    agent.add_argument("--cwd", default=".")
    agent.add_argument("--timeout", type=int, default=120)
    agent.add_argument("prompt")
    fix = sub.add_parser("fix", help="Loop: run tests, let the CLI edit, until they pass")
    fix.add_argument("--tool", choices=["claude-code", "codex"], required=True)
    fix.add_argument("--test", default="pytest -q", help="Test command, split with shlex")
    fix.add_argument("--cwd", default=".")
    fix.add_argument("--rounds", type=int, default=5)
    fix.add_argument("--timeout", type=int, default=300)
    hook = sub.add_parser("install-hook", help="Install an opt-in [AI] post-commit hook")
    hook.add_argument("--cwd", default=".")
    args = parser.parse_args(argv)
    try:
        if args.command == "mark":
            print(json.dumps(add_ai_note(args.commit, args.tool, args.cwd), ensure_ascii=False))
        elif args.command == "ratio":
            print(json.dumps(ratio(args.since, args.until, args.cwd), ensure_ascii=False, indent=2))
        elif args.command == "list":
            print(json.dumps(list_marked(args.since, args.until, args.cwd), ensure_ascii=False, indent=2))
        elif args.command == "run":
            result = run_agent(args.tool, args.prompt, args.cwd, args.timeout)
            print(result.output)
            if result.error:
                print(result.error, file=__import__("sys").stderr)
            return result.exit_code
        elif args.command == "fix":
            if args.rounds < 0:
                parser.error("--rounds must be greater than or equal to 0")
            if args.timeout <= 0:
                parser.error("--timeout must be greater than 0")
            result = auto_fix(
                args.tool, shlex.split(args.test), args.cwd, args.rounds, args.timeout,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result["fixed"] else 1
        elif args.command == "install-hook":
            print(install_hook(args.cwd))
    except (GitError, OSError, ValueError) as exc:
        parser.exit(2, f"error: {exc}\n")
    return 0
