"""Keep only candidates that behave on this machine: FAIL_TO_PASS fails at base_commit and
everything passes with the gold patch. Writes bench/tasks.jsonl.

    python bench/validate.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import swe  # noqa: E402

out = []
for task in swe.load(swe.ROOT / "candidates.jsonl"):
    wd = swe.checkout(task)
    try:
        before = swe.score(task, wd)
        swe.apply_patch(wd, task.patch)
        after = swe.score(task, wd)
    finally:
        swe.remove(wd, task)
    valid = before["f2p_pass"] < 1 and after["resolved"]
    print(f"{task.instance_id:28} before={before['f2p_pass']:.2f}/{before['p2p_pass']:.2f} "
          f"gold={after['f2p_pass']:.2f}/{after['p2p_pass']:.2f} {'OK' if valid else 'DROP'}"
          f"{' ' + after.get('error', '') if not valid else ''}", flush=True)
    if valid:
        out.append(task)

(swe.ROOT / "tasks.jsonl").write_text(
    "".join(json.dumps(t.__dict__) + "\n" for t in sorted(out, key=lambda t: t.created_at))
)
print(f"{len(out)} valid tasks -> bench/tasks.jsonl")
