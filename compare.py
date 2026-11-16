"""Aggregate every arm into one table (Markdown to stdout, JSON to runs/compare.json).

Per task, with the same solver (Codex gpt-6-luna) and hidden-test scoring:

  single     one rollout, stock harness
  DR-E0      Dream-RSI first round, starting policy (4 rollouts, shared by both Dream-RSI arms)
  DR-fixed   E0 + one more round with the fixed policy (RFE baseline), 8 rollouts
  DR-learned E0 + one round with the policy learned by dreaming, <= 8 rollouts
  H2-base    Harness² reference executions with the base harness (k = 2 rollouts)
  H2         Harness² deliverable: the blindly selected final, after 4k = 8 rollouts

Dream-RSI reports the best score found (it queries the hidden tests while searching).
Harness² reports the score of the one deliverable it selected without ground truth.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "bench"))
import swe  # noqa: E402

import os
CLAUDE = os.environ.get("HP_AGENT") == "claude"
W = ROOT / "workspace" / ("claude/dream" if CLAUDE else "dream")
H2 = ROOT / "runs" / ("claude/harness2" if CLAUDE else "harness2")
SINGLE = ROOT / "runs" / ("claude/single" if CLAUDE else "single")


def _scores(f: Path) -> list[float]:
    if not f.is_file():
        return []
    return [float((n.get("raw") or {}).get("combined_score") or 0.0)
            for n in json.loads(f.read_text())["nodes"]]


def _nodes(ws: Path, it: str) -> list[float]:
    return _scores(ws / "history" / it / "raw_scores.json")


def dream(task: str) -> dict:
    # E0 is shared; read it from the E0 workspace, which exists even if a later step failed.
    e0 = _scores(W / "e0" / task / "raw_scores.json")
    fixed2, learned2 = _nodes(W / "baseline" / task, "iter001"), _nodes(W / "dream_rsi" / task, "iter001")
    first = lambda xs: next((i + 1 for i, x in enumerate(xs) if x == 1.0), None)
    return {
        "e0_best": max(e0, default=None),
        "fixed_best": max(e0 + fixed2, default=None) if fixed2 else None,
        # None = the learning step did not complete (no learned round to report)
        "learned_best": max(e0 + learned2, default=None) if learned2 else None,
        "fixed_rollouts": len(e0) + len(fixed2), "learned_rollouts": len(e0) + len(learned2),
        "first_success": first(e0),
    }


def harness2(task: str) -> dict:
    sums = list((H2 / "runs").glob(f"*/{task}/summary.json"))
    scores = {}
    for f in (H2 / "scores").glob(f"*__{task}__*.json"):
        d = json.loads(f.read_text())
        scores[d["run_id"].rsplit("/", 1)[-1]] = d
    base = [scores[k]["score"] for k in sorted(scores) if k.startswith("base")]
    out = {"base_mean": sum(base) / len(base) if base else None, "rollouts": len(scores)}
    if sums:
        sel = json.loads(sums[0].read_text()).get("selections", {}).get("agg", {})
        lbl = sel.get("chosen_label")
        out.update(chosen=lbl, final=scores.get(lbl, {}).get("score"),
                   any_rollout=max((s["score"] for s in scores.values()), default=None))
    return out


def single(task: str) -> float | None:
    f = SINGLE / task / "result.json"
    return json.loads(f.read_text())["score"] if f.is_file() else None


def fmt(x) -> str:
    return "–" if x is None else (f"{x:.2f}" if isinstance(x, float) else str(x))


if __name__ == "__main__":
    rows = []
    for t in swe.load():
        rows.append({"task": t.instance_id, "single": single(t.instance_id),
                     "dream": dream(t.instance_id), "harness2": harness2(t.instance_id)})
    (ROOT / "runs" / ("compare-claude.json" if CLAUDE else "compare.json")).write_text(json.dumps(rows, indent=1))
    hdr = "| task | single | DR-E0 (4) | DR-fixed (8) | DR-learned | H2-base | H2 final (8) | H2 best rollout |"
    print(hdr)
    print("|---|---|---|---|---|---|---|---|")
    tot = {k: [] for k in ("single", "e0", "fixed", "learned", "h2b", "h2")}
    for r in rows:
        d, h = r["dream"], r["harness2"]
        print(f"| {r['task'].split('-')[-1]} | {fmt(r['single'])} | {fmt(d['e0_best'])} | {fmt(d['fixed_best'])} | "
              f"{fmt(d['learned_best'])} ({d['learned_rollouts']}) | {fmt(h.get('base_mean'))} | "
              f"{fmt(h.get('final'))} | {fmt(h.get('any_rollout'))} |")
        for k, v in (("single", r["single"]), ("e0", d["e0_best"]), ("fixed", d["fixed_best"]),
                     ("learned", d["learned_best"]), ("h2b", h.get("base_mean")), ("h2", h.get("final"))):
            if v is not None:
                tot[k].append(v)
    solved = lambda xs: f"{sum(x == 1.0 for x in xs)}/{len(xs)}" if xs else "–"
    print(f"| **resolved** | {solved(tot['single'])} | {solved(tot['e0'])} | {solved(tot['fixed'])} | "
          f"{solved(tot['learned'])} | {fmt(sum(tot['h2b']) / len(tot['h2b'])) if tot['h2b'] else '–'} (mean) | "
          f"{solved(tot['h2'])} | |")
