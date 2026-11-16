"""Run Codex headless in a workspace and record usage. Used by every arm."""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SHIM = ROOT / "agents" / "codex-shim"
MODEL = "gpt-6-luna"


def task_prompt(task, python: str) -> str:
    """The task exactly as every arm's solver receives it."""
    return (
        f"You are in a checkout of the `{task.repo}` repository. Resolve the GitHub issue below "
        f"by editing the library source code.\n\n"
        f"- Do not edit or add files under `tests/`; hidden tests will check your change.\n"
        f"- You may run the existing tests: `{python} -m pytest tests/...`\n"
        f"- There is no network access.\n\n"
        f"# Issue\n\n{task.problem_statement}\n"
    )


def run(workspace: Path, prompt: str, log_dir: Path, *, timeout: int = 1800) -> dict:
    """One Codex rollout. Returns usage and status; events are saved to log_dir/events.jsonl."""
    log_dir.mkdir(parents=True, exist_ok=True)
    (log_dir / "prompt.md").write_text(prompt)
    cmd = [str(SHIM), "exec", "--skip-git-repo-check", "--json", "-s", "workspace-write",
           "-m", MODEL, "-C", str(workspace), "-o", str(log_dir / "last_message.txt"), prompt]
    t0 = time.time()
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        out, code = proc.stdout, proc.returncode
    except subprocess.TimeoutExpired as exc:
        out, code = (exc.stdout or b"").decode() if isinstance(exc.stdout, bytes) else (exc.stdout or ""), -1
    wall = time.time() - t0
    (log_dir / "events.jsonl").write_text(out)
    usage = {"input_tokens": 0, "cached_input_tokens": 0, "output_tokens": 0, "reasoning_output_tokens": 0}
    commands = 0
    for line in out.splitlines():
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if ev.get("type") == "turn.completed":
            for k in usage:
                usage[k] += ev.get("usage", {}).get(k, 0) or 0
        elif ev.get("type") == "item.completed" and ev.get("item", {}).get("type") == "command_execution":
            commands += 1
    return {"exit": code, "wall_s": round(wall, 1), "commands": commands, **usage}
