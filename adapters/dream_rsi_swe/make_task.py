"""Turn one SWE-rebench task into a Dream-RSI task directory.

Dream-RSI evolves a single program file. Here the program is the fix itself: a list
of exact-match edits. The evaluator applies them to a clean snapshot and runs the
hidden tests, so `combined_score` is the graded SWE score.

    python adapters/dream_rsi_swe/make_task.py tobymao__sqlglot-6389 [...]
    -> workspace/dream_tasks/<id>/{<id>.txt, init_program.py, evaluator.py}
       workspace/refs/<id>/      read-only reference checkout for the agent
"""

from __future__ import annotations

import stat
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "bench"))
import swe  # noqa: E402

INIT = '''# EVOLVE-BLOCK-START
# Each edit is (path relative to the repository root, exact old text, new text).
# `old` must occur exactly once in the file; use "" as `old` to create a new file.
EDITS: list[tuple[str, str, str]] = []
# EVOLVE-BLOCK-END
'''

EVALUATOR = '''"""Apply EDITS to a clean snapshot of {iid} and score it on the hidden tests."""
import importlib.util
import sys
from pathlib import Path

sys.path.insert(0, {bench!r})
import swe

TASK_ID = {iid!r}


def _apply(repo: Path, edits) -> None:
    for i, (path, old, new) in enumerate(edits):
        f = (repo / path).resolve()
        if repo.resolve() not in f.parents:
            raise ValueError(f"edit {{i}}: path escapes the repository: {{path}}")
        if path.startswith("tests/"):
            raise ValueError(f"edit {{i}}: editing tests is not allowed: {{path}}")
        if old == "":
            if f.exists():
                raise ValueError(f"edit {{i}}: {{path}} already exists")
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(new)
            continue
        text = f.read_text()
        n = text.count(old)
        if n != 1:
            raise ValueError(f"edit {{i}}: old text found {{n}} times in {{path}} (must be exactly 1)")
        f.write_text(text.replace(old, new, 1))


def evaluate(program_path):
    spec = importlib.util.spec_from_file_location("candidate", program_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    edits = list(getattr(mod, "EDITS", []))
    if not edits:
        return {{"combined_score": 0.0, "error": "EDITS is empty"}}
    task = swe.get(TASK_ID)
    wd = swe.checkout(task)
    try:
        try:
            _apply(wd, edits)
        except Exception as exc:
            return {{"combined_score": 0.0, "error": str(exc)[:300]}}
        r = swe.score(task, wd)
    finally:
        swe.remove(wd)
    # Only fractions go back to the agent: no test names or output.
    return {{"combined_score": r["score"], "f2p_pass": r["f2p_pass"], "p2p_pass": r["p2p_pass"],
            "resolved": r["resolved"]}}
'''

PROBLEM = """{prompt}
# How to submit

Write the fix into the program file as `EDITS`: a list of `(path, old, new)` tuples, paths relative to the repository root. `old` must match the current file text exactly once.

- The repository at the starting commit is at `{ref}` (read-only). Read it to understand the code.
- To try a change, copy it first, e.g. `cp -R {ref} /tmp/try-$$`, edit the copy, and run tests there with `PYTHONDONTWRITEBYTECODE=1 {python} -m pytest -p no:cacheprovider tests/...`.
- The evaluator applies `EDITS` to a clean copy and runs hidden tests. The score is the fraction of the target tests that pass, or 0 if any existing test breaks.
"""


def make(task: swe.Task) -> Path:
    sys.path.insert(0, str(ROOT / "agents"))
    import codex_run

    ref = ROOT / "workspace" / "refs" / task.instance_id
    if not ref.exists():
        swe.checkout(task, ref)
        for p in [ref, *ref.rglob("*")]:  # read-only reference
            if not p.is_symlink():
                p.chmod(p.stat().st_mode & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))
    d = ROOT / "workspace" / "dream_tasks" / task.instance_id
    d.mkdir(parents=True, exist_ok=True)
    prompt = codex_run.task_prompt(task, swe.PYTHON).split("# Issue", 1)
    issue = "# Issue" + prompt[1]
    (d / f"{task.instance_id}.txt").write_text(PROBLEM.format(prompt=issue, ref=ref, python=swe.PYTHON))
    (d / "init_program.py").write_text(INIT)
    (d / "evaluator.py").write_text(EVALUATOR.format(iid=task.instance_id, bench=str(ROOT / "bench")))
    return d


if __name__ == "__main__":
    ids = sys.argv[1:] or [t.instance_id for t in swe.load()]
    for i in ids:
        print(make(swe.get(i)))
