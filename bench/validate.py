"""Keep only candidates that behave on this machine: FAIL_TO_PASS fails at base_commit and
everything passes with the gold patch.

    python bench/validate.py                                   # candidates.jsonl -> tasks.jsonl
    python bench/validate.py --src X.jsonl --dst Y.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import swe  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--src", default=str(swe.ROOT / "candidates.jsonl"))
ap.add_argument("--dst", default=str(swe.ROOT / "tasks.jsonl"))
args = ap.parse_args()

out = []
for task in swe.load(args.src):
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

Path(args.dst).write_text(
    "".join(json.dumps(t.__dict__) + "\n" for t in sorted(out, key=lambda t: t.created_at))
)
print(f"{len(out)} valid tasks -> {args.dst}")
