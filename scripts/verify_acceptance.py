"""Black-box acceptance checks. Uses real Git/CLI; never calls an AI service."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import uuid
from datetime import datetime
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=PROJECT / "validation_runs")
    args = parser.parse_args()
    folder = args.output_root.resolve() / (
        datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8]
    )
    folder.mkdir(parents=True)
    env = os.environ.copy()
    env["PYTHONPATH"] = str(PROJECT / "src")
    # Keep source selection consistent in child processes, including Git hooks.
    env["PYTHONIOENCODING"] = "utf-8"
    # Git hooks on Windows invoke 'python'; make it resolve to this interpreter.
    env["PATH"] = str(Path(sys.executable).parent) + os.pathsep + env.get("PATH", "")
    report = {"scope": "real Git and local CLI; no real model calls",
              "run_directory": str(folder), "checks": []}
    log = []

    def command(argv, cwd):
        proc = subprocess.run(
            [str(v) for v in argv], cwd=cwd, env=env, capture_output=True,
            text=True, encoding="utf-8", errors="replace", timeout=60,
        )
        log.append({"argv": [str(v) for v in argv], "cwd": str(cwd),
                    "exit_code": proc.returncode, "stdout": proc.stdout,
                    "stderr": proc.stderr})
        if proc.returncode:
            raise RuntimeError(f"Command failed ({proc.returncode}): {argv}\n{proc.stderr}")
        return proc.stdout.strip()

    def git(repo, *argv):
        return command(["git", *argv], repo)

    def cli(repo, *argv):
        return command([sys.executable, "-m", "ai_code_metrics", *argv], repo)

    def expect(label, actual, expected):
        passed = actual == expected
        report["checks"].append(
            {"name": label, "passed": passed, "expected": expected, "actual": actual}
        )
        print(f"{'PASS' if passed else 'FAIL'} {label}", flush=True)
        if not passed:
            raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")

    def new_repo(name):
        repo = folder / name
        repo.mkdir()
        # Do not copy any personal hooks from Git's template directory.
        git(repo, "-c", "init.templateDir=", "init", "-q")
        for key, value in [
            ("user.name", "Acceptance Check"), ("user.email", "check@example.invalid"),
            ("commit.gpgsign", "false"), ("core.autocrlf", "false"),
            ("core.hooksPath", str(repo / ".git" / "hooks")),
        ]:
            git(repo, "config", key, value)
        return repo

    def write(repo, name, text):
        (repo / name).write_text(text, encoding="utf-8", newline="\n")

    def commit(repo, message):
        git(repo, "add", ".")
        git(repo, "commit", "-qm", message)
        return git(repo, "rev-parse", "HEAD")

    def measure(repo, since=None, until="HEAD"):
        argv = ["ratio", "--cwd", str(repo), "--until", until]
        if since:
            argv.extend(["--since", since])
        # Execute outside target repo to verify --cwd routing.
        return json.loads(cli(PROJECT, *argv))

    def numbers(value):
        return {key: value[key] for key in
                ("commits", "ai_commits", "total_added", "ai_added", "ratio")}

    try:
        repo = new_repo("metrics-repo")
        write(repo, "base.txt", "base\n")
        base = commit(repo, "initial")
        expect("unmarked root commit", numbers(measure(repo)),
               dict(commits=1, ai_commits=0, total_added=1, ai_added=0, ratio=0.0))
        write(repo, "ai.txt", "one\ntwo\nthree\n")
        ai = commit(repo, "[AI] simulated contribution")
        before_message = git(repo, "log", "-1", "--pretty=%B")
        note = json.loads(cli(PROJECT, "mark", "--cwd", str(repo),
                              "--commit", ai, "--tool", "simulated"))
        expect("note snapshot", {key: note[key] for key in ("tool", "added", "deleted", "files")},
               dict(tool="simulated", added=3, deleted=0, files=1))
        expect("notes do not change commit message", git(repo, "log", "-1", "--pretty=%B"),
               before_message)
        expect("dedicated notes ref", json.loads(git(
            repo, "notes", "--ref=refs/notes/ai-code-metrics", "show", ai))["added"], 3)
        write(repo, "human.txt", "manual\n")
        human = commit(repo, "human contribution")
        expected = dict(commits=2, ai_commits=1, total_added=4, ai_added=3, ratio=0.75)
        expect("hand calculation: 3 / 4", numbers(measure(repo, base)), expected)
        listing = json.loads(cli(PROJECT, "list", "--cwd", str(repo), "--since", base))
        expect("list only marked commit", [row["commit"] for row in listing], [ai])
        expect("exclusive since and inclusive until", numbers(measure(repo, base, ai)),
               dict(commits=1, ai_commits=1, total_added=3, ai_added=3, ratio=1.0))
        expect("empty range", numbers(measure(repo, human, human)),
               dict(commits=0, ai_commits=0, total_added=0, ai_added=0, ratio=None))
        write(repo, "base.txt", "base\nuncommitted\n")
        expect("uncommitted changes excluded", numbers(measure(repo, base)), expected)
        write(repo, "base.txt", "base\n")
        (repo / "binary.bin").write_bytes(b"\x00\x01\x02\xff")
        binary = commit(repo, "[AI] binary change")
        cli(PROJECT, "mark", "--cwd", str(repo), "--commit", binary, "--tool", "simulated")
        expect("binary adds zero text lines", numbers(measure(repo, base)),
               dict(commits=3, ai_commits=2, total_added=4, ai_added=3, ratio=0.75))
        (repo / "human.txt").unlink()
        commit(repo, "delete only")
        expect("deletion does not count as added lines", numbers(measure(repo, base)),
               dict(commits=4, ai_commits=2, total_added=4, ai_added=3, ratio=0.75))
        main_branch = git(repo, "branch", "--show-current")
        git(repo, "checkout", "-qb", "check-feature")
        write(repo, "branch.txt", "branch one\nbranch two\n")
        commit(repo, "branch contribution")
        git(repo, "checkout", main_branch)
        write(repo, "main.txt", "main one\n")
        commit(repo, "main contribution")
        git(repo, "-c", "merge.gpgsign=false", "merge", "--no-ff", "check-feature",
            "-m", "[AI] merge branch")
        cli(PROJECT, "mark", "--cwd", str(repo), "--tool", "simulated")
        expect("marked merge excluded from both totals", numbers(measure(repo, base)),
               dict(commits=6, ai_commits=2, total_added=7, ai_added=3, ratio=0.4286))

        hook_repo = new_repo("hook-repo")
        write(hook_repo, "base.txt", "base\n")
        hook_base = commit(hook_repo, "initial")
        cli(hook_repo, "install-hook")
        write(hook_repo, "ai.txt", "one\ntwo\n")
        hook_ai = commit(hook_repo, "[AI] hook check")
        expect("hook automatically writes note", json.loads(git(
            hook_repo, "notes", "--ref=refs/notes/ai-code-metrics", "show", hook_ai))["tool"],
            "hook")
        write(hook_repo, "human.txt", "manual\n")
        commit(hook_repo, "ordinary commit")
        expect("hook leaves ordinary commit unmarked", numbers(measure(hook_repo, hook_base)),
               dict(commits=2, ai_commits=1, total_added=3, ai_added=2, ratio=0.6667))
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
    report["passed"] = "error" not in report and all(c["passed"] for c in report["checks"])
    report["check_count"] = len(report["checks"])
    (folder / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (folder / "commands.json").write_text(
        json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Report: {folder / 'report.json'}")
    if not report["passed"]:
        print(report.get("error", "Check failed"), file=sys.stderr)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
