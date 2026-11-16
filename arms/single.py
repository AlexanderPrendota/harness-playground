"""Baseline arm: one Codex rollout per task with the stock harness.

    python arms/single.py [--tasks ID ...] [--out runs/single]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "bench"), str(ROOT / "agents")]
import codex_run  # noqa: E402
import swe  # noqa: E402


def solve(task, out: Path) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    wd = swe.checkout(task)
    try:
        usage = codex_run.run(wd, codex_run.task_prompt(task, swe.PYTHON), out)
        patch = swe.diff(wd)
        (out / "patch.diff").write_text(patch)
        result = {"task": task.instance_id, **usage, "patch_lines": patch.count("\n"), **swe.score(task, wd)}
    finally:
        swe.remove(wd)
    (out / "result.json").write_text(json.dumps(result, indent=1))
    return result


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", nargs="*")
    ap.add_argument("--out", default=str(ROOT / "runs" / "single"))
    a = ap.parse_args()
    for task in swe.load():
        if a.tasks and task.instance_id not in a.tasks:
            continue
        r = solve(task, Path(a.out) / task.instance_id)
        print(json.dumps({k: r[k] for k in ("task", "resolved", "f2p_pass", "p2p_pass", "input_tokens",
                                             "output_tokens", "wall_s", "commands")}), flush=True)
