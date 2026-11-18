"""SWE-rebench task runner for macOS without Docker.

A task is a snapshot of a local mirror at `base_commit`; at scoring time its
`test_patch` is applied, and the FAIL_TO_PASS / PASS_TO_PASS tests run with
pytest in a shared uv venv (sqlglot is pure Python, so no per-task image).

score(task, workdir) -> dict with:
  f2p_pass   fraction of FAIL_TO_PASS tests that pass
  p2p_pass   fraction of PASS_TO_PASS tests that pass
  resolved   all F2P and all P2P pass (the SWE-bench criterion)
  score      f2p_pass if p2p_pass == 1 else 0   (graded score for Dream-RSI)
"""

from __future__ import annotations

import fcntl
import json
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MIRRORS = Path(os.environ.get("HP_MIRRORS", str(ROOT.parent / "data")))
PYTHON = os.environ.get("HP_TEST_PYTHON", str(ROOT.parent / ".venv-tests" / "bin" / "python"))


@dataclass
class Task:
    instance_id: str
    repo: str
    base_commit: str
    problem_statement: str
    patch: str
    test_patch: str
    FAIL_TO_PASS: list[str]
    PASS_TO_PASS: list[str]
    test_cmd: str
    created_at: str = ""

    @property
    def mirror(self) -> Path:
        return MIRRORS / self.repo.split("/")[1]


def load(path: Path | str = ROOT / "tasks.jsonl") -> list[Task]:
    return [Task(**json.loads(line)) for line in Path(path).read_text().splitlines() if line.strip()]


def get(instance_id: str) -> Task:
    """Find a task by id in any task list under bench/ (tasks.jsonl first)."""
    files = [ROOT / "tasks.jsonl"] + sorted(f for f in ROOT.glob("*.jsonl") if f.name != "tasks.jsonl")
    for f in files:
        for t in load(f):
            if t.instance_id == instance_id:
                return t
    raise KeyError(instance_id)


def _git(*args: str, cwd: Path, input: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, input=input, text=True, capture_output=True)


def checkout(task: Task, dest: Path | None = None) -> Path:
    """Snapshot of the repo at base_commit with a fresh one-commit git history.

    No test_patch (the agent must not see the hidden tests) and no upstream history
    (later commits contain the actual fix).
    """
    dest = Path(dest or tempfile.mkdtemp(prefix=f"{task.instance_id}-"))
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    # Arms run in parallel and share one mirror: serialize the fetch of a missing commit.
    with open(task.mirror / ".hp-fetch.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if _git("cat-file", "-e", f"{task.base_commit}^{{commit}}", cwd=task.mirror).returncode:
            _git("fetch", "-q", "origin", task.base_commit, cwd=task.mirror)
    archive = subprocess.run(["git", "archive", task.base_commit], cwd=task.mirror, capture_output=True)
    if archive.returncode:
        raise RuntimeError(archive.stderr.decode()[:400])
    subprocess.run(["tar", "-x", "-C", str(dest)], input=archive.stdout, check=True)
    for args in (("init", "-q"), ("add", "-A"),
                 ("-c", "user.name=task", "-c", "user.email=task@local", "commit", "-q", "-m", "base")):
        _git(*args, cwd=dest)
    return dest


def remove(workdir: Path, task: Task | None = None) -> None:
    shutil.rmtree(workdir, ignore_errors=True)


def diff(workdir: Path) -> str:
    """The agent's change as a patch (tracked and new files)."""
    _git("add", "-A", cwd=workdir)
    return _git("diff", "--cached", "--binary", cwd=workdir).stdout


def apply_patch(workdir: Path, patch: str) -> None:
    r = _git("apply", "--whitespace=nowarn", "-", cwd=workdir, input=patch)
    if r.returncode:
        raise RuntimeError(f"git apply failed: {r.stderr[:400]}")


_RESULT = re.compile(r"^(PASSED|FAILED|ERROR|XFAIL|XPASS|SKIPPED) (\S+)", re.M)


def run_tests(workdir: Path, tests: list[str], timeout: int = 600) -> dict[str, str]:
    """Run pytest node ids; return {node_id: status}. Missing ids count as FAILED."""
    files = sorted({t.split("::")[0] for t in tests})
    env = {**os.environ, "PYTHONPATH": str(workdir)}
    proc = subprocess.run(
        [PYTHON, "-m", "pytest", "--no-header", "-rA", "--tb=no", "--color=no",
         "-p", "no:cacheprovider", *files],
        cwd=workdir, env=env, text=True, capture_output=True, timeout=timeout,
    )
    seen = {m.group(2): m.group(1) for m in _RESULT.finditer(proc.stdout)}
    return {t: seen.get(t, "FAILED") for t in tests}


def score(task: Task, workdir: Path) -> dict:
    """Score the code in `workdir` against the hidden tests, on a scratch copy."""
    scratch = Path(tempfile.mkdtemp(prefix="score-"))
    try:
        shutil.copytree(workdir, scratch / "repo", ignore=shutil.ignore_patterns(".git"))
        repo = scratch / "repo"
        apply_patch(repo, task.test_patch)
        res = run_tests(repo, task.FAIL_TO_PASS + task.PASS_TO_PASS)
    except Exception as exc:  # a broken candidate scores 0
        return {"f2p_pass": 0.0, "p2p_pass": 0.0, "resolved": False, "score": 0.0, "error": str(exc)[:400]}
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    ok = lambda ts: sum(res[t] in ("PASSED", "XFAIL") for t in ts) / max(len(ts), 1)
    f2p, p2p = ok(task.FAIL_TO_PASS), ok(task.PASS_TO_PASS)
    return {"f2p_pass": f2p, "p2p_pass": p2p, "resolved": f2p == 1 and p2p == 1,
            "score": f2p if p2p == 1 else 0.0}
