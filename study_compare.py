"""Tables for the follow-up studies (not part of the main comparison).

    python study_compare.py calib  --tasks-file F --runs runs/calib/run1 runs/calib/run2 [--extra-single runs/single]
    python study_compare.py library --tasks-file F --carry runs/h2-carry --reset runs/h2-reset
    python study_compare.py dream  --tasks-file F --ws workspace/study-dream
"""

from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "bench"))
import swe  # noqa: E402


def _single(run_dir: Path, tid: str):
    f = run_dir / tid / "result.json"
    return json.loads(f.read_text()) if f.is_file() else None


def calib(a) -> None:
    print("| task | F2P | score per run | solved | mean score |")
    print("|---|---|---|---|---|")
    for t in swe.load(a.tasks_file):
        rs = [r for r in (_single(Path(d), t.instance_id) for d in a.runs) if r]
        sc = [r["score"] for r in rs]
        if not sc:
            continue
        print(f"| {t.instance_id.split('-')[-1]} | {len(t.FAIL_TO_PASS)} | {' '.join(f'{x:.2f}' for x in sc)} | "
              f"{sum(x == 1 for x in sc)}/{len(sc)} | {sum(sc)/len(sc):.2f} |")


def _h2(root: Path, tid: str) -> dict:
    sc = {}
    for f in glob.glob(str(root / "scores" / f"*__{tid}__*.json")):
        d = json.loads(Path(f).read_text())
        sc[d["run_id"].rsplit("/", 1)[-1]] = d["score"]
    out = {"scores": sc}
    sums = glob.glob(str(root / "runs" / "*" / tid / "summary.json"))
    if sums:
        out["chosen"] = json.loads(Path(sums[0]).read_text()).get("selections", {}).get("agg", {}).get("chosen_label")
    return out


def library(a) -> None:
    tasks = swe.load(a.tasks_file)
    print("| # | task | carry: base / probes / final | reset: base / probes / final |")
    print("|---|---|---|---|")
    agg = {"carry": [[], [], []], "reset": [[], [], []]}
    for i, t in enumerate(tasks, 1):
        cells = []
        for arm, root in (("carry", Path(a.carry)), ("reset", Path(a.reset))):
            r = _h2(root, t.instance_id)
            s = r["scores"]
            mean = lambda ks: (sum(s[k] for k in ks) / len(ks)) if ks else None
            base = mean([k for k in s if k.startswith("base")])
            probes = mean([k for k in s if k.startswith(("inv", "dom"))])
            final = s.get(r.get("chosen")) if r.get("chosen") else None
            for j, v in enumerate((base, probes, final)):
                if v is not None:
                    agg[arm][j].append((i, v))
            f = lambda v: "–" if v is None else f"{v:.2f}"
            cells.append(f"{f(base)} / {f(probes)} / {f(final)}")
        print(f"| {i} | {t.instance_id.split('-')[-1]} | {cells[0]} | {cells[1]} |")
    n = len(tasks)
    for arm in ("carry", "reset"):
        for half, lo, hi in (("first half", 1, n // 2), ("second half", n // 2 + 1, n)):
            vals = [[v for i, v in col if lo <= i <= hi] for col in agg[arm]]
            m = lambda xs: f"{sum(xs)/len(xs):.2f}" if xs else "–"
            print(f"{arm:5} {half:11}: base {m(vals[0])}  probes {m(vals[1])}  final {m(vals[2])}  (n={len(vals[2])})")


def _rounds(ws: Path) -> list[list[float]]:
    out = []
    for f in sorted((ws / "history").glob("iter*/raw_scores.json")):
        out.append([float((n.get("raw") or {}).get("combined_score") or 0) for n in json.loads(f.read_text())["nodes"]])
    return out


def dream(a) -> None:
    W = Path(a.ws)
    print("| task | E0 best | learned: best per round | fixed: best per round | learned total best | fixed total best | promoted |")
    print("|---|---|---|---|---|---|---|")
    for t in swe.load(a.tasks_file):
        e0f = W / "e0" / t.instance_id / "raw_scores.json"
        if not e0f.is_file():
            continue
        e0 = [float((n.get("raw") or {}).get("combined_score") or 0) for n in json.loads(e0f.read_text())["nodes"]]
        L, F = _rounds(W / "dream_rsi" / t.instance_id)[1:], _rounds(W / "baseline" / t.instance_id)[1:]
        log = W / f"{t.instance_id}.dream.log"
        promoted = sum(1 for l in log.read_text().splitlines() if l.strip().startswith("selected") and "incumbent" not in l) if log.is_file() else 0
        kept = sum(1 for l in log.read_text().splitlines() if "incumbent kept" in l) if log.is_file() else 0
        f = lambda rs: " ".join(f"{max(r):.2f}" for r in rs) or "–"
        tb = lambda rs: f"{max([max(e0)] + [max(r) for r in rs]):.2f}"
        print(f"| {t.instance_id.split('-')[-1]} | {max(e0):.2f} | {f(L)} | {f(F)} | {tb(L)} | {tb(F)} | {promoted} promoted, {kept} kept |")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("study", choices=("calib", "library", "dream"))
    ap.add_argument("--tasks-file", required=True)
    ap.add_argument("--runs", nargs="*", default=[])
    ap.add_argument("--carry"); ap.add_argument("--reset"); ap.add_argument("--ws")
    a = ap.parse_args()
    {"calib": calib, "library": library, "dream": dream}[a.study](a)
