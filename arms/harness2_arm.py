"""Harness² arm: parallel task-level recursion (k=2 -> 4k = 8 Codex rollouts per task) over a
stream of tasks from one repository, threading the experience library forward.

    python arms/harness2_arm.py [--k 2] [--tasks ID ...] [--tasks-file F] [--library carry|reset] [--out DIR]

--library reset gives every task an empty experience library (ablation of the
harnessing-level recursion); the default carries the library forward across tasks.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "adapters"), str(ROOT / "bench"), str(ROOT / "agents")]
import swe  # noqa: E402
from harness2_swe import CodexProposer, SWEAdapter  # noqa: E402

from harness2.core.schedule import run_domain  # noqa: E402

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--k", type=int, default=2)
    ap.add_argument("--tasks", nargs="*")
    ap.add_argument("--tasks-file", default=None, help="task list (default: bench/tasks.jsonl)")
    ap.add_argument("--library", choices=("carry", "reset"), default="carry")
    import codex_run
    ap.add_argument("--out", default=str(ROOT / "runs" / ("claude/harness2" if codex_run.AGENT == "claude" else "harness2")))
    a = ap.parse_args()
    src = swe.load(a.tasks_file) if a.tasks_file else swe.load()
    tasks = [t for t in src if not a.tasks or t.instance_id in a.tasks]
    root = Path(a.out).resolve()
    adapter = SWEAdapter(root, tasks)
    prop = CodexProposer(adapter.spec.channels["proposer"], audit_dir=root / "audit")
    domain = adapter.domain_of(tasks[0].instance_id)
    common = dict(adapter=adapter, prop=prop, runs_root=adapter.spec.runs_root, modes=("agg",))
    if a.library == "carry":
        result = run_domain(domain, adapter.tasks(), a.k, library_root=root / "library" / f"k{a.k}", **common)
    else:  # one fresh library per task: nothing carries over
        parts = [run_domain(domain, [t], a.k, library_root=root / "library" / f"k{a.k}" / t, **common)
                 for t in adapter.tasks()]
        result = {"done": sum(p.get("done", 0) for p in parts), "failed": sum(p.get("failed", 0) for p in parts),
                  "tasks": [x for p in parts for x in p.get("tasks", [])]}
    (root / "domain.json").write_text(json.dumps(result, indent=2, default=str))
    print(json.dumps({"done": result.get("done"), "failed": result.get("failed")}))
