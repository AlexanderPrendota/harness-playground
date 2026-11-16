"""Harness² arm: parallel task-level recursion (k=2 -> 4k = 8 Codex rollouts per task) over a
stream of tasks from one repository, threading the experience library forward.

    python arms/harness2_arm.py [--k 2] [--tasks ID ...] [--out runs/harness2]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "adapters"), str(ROOT / "bench")]
import swe  # noqa: E402
from harness2_swe import CodexProposer, SWEAdapter  # noqa: E402

from harness2.core.schedule import run_domain  # noqa: E402

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--k", type=int, default=2)
    ap.add_argument("--tasks", nargs="*")
    ap.add_argument("--out", default=str(ROOT / "runs" / "harness2"))
    a = ap.parse_args()
    tasks = [t for t in swe.load() if not a.tasks or t.instance_id in a.tasks]
    root = Path(a.out).resolve()
    adapter = SWEAdapter(root, tasks)
    prop = CodexProposer(adapter.spec.channels["proposer"], audit_dir=root / "audit")
    result = run_domain(
        adapter.domain_of(tasks[0].instance_id),
        adapter.tasks(),
        a.k,
        adapter=adapter,
        prop=prop,
        runs_root=adapter.spec.runs_root,
        library_root=root / "library" / f"k{a.k}",
        modes=("agg",),
    )
    (root / "domain.json").write_text(json.dumps(result, indent=2, default=str))
    print(json.dumps({"done": result.get("done"), "failed": result.get("failed")}))
