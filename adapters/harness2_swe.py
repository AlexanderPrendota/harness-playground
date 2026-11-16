"""Harness² BenchmarkAdapter for the SWE-rebench slice, with Codex as the executor.

- Harness layout: Harness²'s own Codex surface (AGENTS.md, .agents/skills, scripts, .codex).
- Executor: our `codex exec` runner under the user's Codex login. The bundled Codex substrate
  expects a configured Responses endpoint, so only its surface is reused.
- Improver/selector: Codex as well (`CodexProposer`), so both methods improve with the same
  model as they solve. Harness² ships OpenCode and Claude CLI channels only; `CodexProposer`
  replaces the Claude CLI call with `codex exec` and keeps everything else.
- Hidden tests never enter a run directory: scores go to `<runs_root>/../scores/`.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "bench"), str(ROOT / "agents")]
import codex_run  # noqa: E402
import swe  # noqa: E402

from harness2 import config  # noqa: E402
from harness2.core import tree as harness_tree  # noqa: E402
from harness2.core.proposer import Proposer  # noqa: E402
from harness2.core.spec import BenchPrompts, BenchSpec, ChannelSpec  # noqa: E402
from harness2.substrate.codex import CODEX_ROOT_ENTRIES, CodexSubstrate  # noqa: E402

IMPROVER_MODEL = codex_run.MODEL

# Same text for every arm (single run, Dream-RSI, Harness² base): a neutral starting harness.
BASE_AGENTS_MD = (
    "You are a software engineer working in this repository. "
    "Make the smallest correct change to the library source that resolves the request.\n"
)


@dataclass
class CodexProposer(Proposer):
    """Improver/selector sessions on Codex. Rides the `claude_cli` channel slot of the stock
    Proposer (same retries, cache, audit, harvest) and swaps only the CLI invocation."""

    def _claude_cli(self, cwd: Path, mission: str, system: str, wall: int) -> tuple[str, float, str]:
        prompt = f"# SYSTEM INSTRUCTIONS\n\n{system}\n\n# END\n\n{mission}" if system else mission
        last = Path(tempfile.mkstemp(prefix="cx-prop-", suffix=".txt")[1])
        try:
            p = subprocess.run(
                [str(codex_run.SHIM), "exec", "--skip-git-repo-check", "--json", "-s", "workspace-write",
                 "-m", self.spec.model, "-C", str(cwd), "-o", str(last), prompt],
                capture_output=True, text=True, timeout=wall,
            )
            text = last.read_text() if last.is_file() else ""
            err = "" if text.strip() else f"rc={p.returncode}: {(p.stderr or p.stdout or '')[-300:]}"
            return text, 0.0, err
        finally:
            last.unlink(missing_ok=True)


def _to_claude_layout(wd: Path) -> None:
    """Map the Codex harness layout onto Claude Code's: AGENTS.md -> CLAUDE.md,
    .agents/skills -> .claude/skills, .codex/hooks.json -> .claude/settings.json (same hook
    schema), sub_agents/<n>/AGENT.md -> .claude/agents/<n>.md. The editors keep working on
    the Codex layout, so both agents share one harness surface. As with Codex, the harness's
    instruction file replaces any AGENTS.md/CLAUDE.md the repository ships."""
    if (wd / "AGENTS.md").is_file():
        dst = wd / "CLAUDE.md"
        if dst.is_symlink() or dst.exists():  # some repos ship CLAUDE.md -> AGENTS.md
            dst.unlink()
        shutil.copy2(wd / "AGENTS.md", dst)
    if (wd / ".agents" / "skills").is_dir():
        shutil.copytree(wd / ".agents" / "skills", wd / ".claude" / "skills", dirs_exist_ok=True)
    hooks = wd / ".codex" / "hooks.json"
    if hooks.is_file():
        (wd / ".claude").mkdir(exist_ok=True)
        (wd / ".claude" / "settings.json").write_text(hooks.read_text())
    for agent in (wd / "sub_agents").glob("*/AGENT.md"):
        (wd / ".claude" / "agents").mkdir(parents=True, exist_ok=True)
        shutil.copy2(agent, wd / ".claude" / "agents" / f"{agent.parent.name}.md")


class SWEAdapter:
    def __init__(self, root: Path, tasks: list[swe.Task]):
        self.root = Path(root)
        self._tasks = {t.instance_id: t for t in tasks}
        self._order = [t.instance_id for t in tasks]
        self.substrate = CodexSubstrate()
        channel = ChannelSpec("claude_cli", IMPROVER_MODEL)  # slot reused by CodexProposer
        self.spec = BenchSpec(
            name="swe-rebench",
            runs_root=self.root / "runs",
            install_mode="codex_root",
            prompts=BenchPrompts(
                work="resolve a reported bug in a Python library by changing its source code",
                domain_word="repository",
                deliverable_word="patch",
            ),
            channels={"proposer": channel, "selector": channel},
        )
        self.scores_dir = self.root / "scores"
        base = {"AGENTS.md": BASE_AGENTS_MD}
        harness_tree.write_tree(self.substrate.surface(), base, self.base_harness(), stubs=True)

    # -- task stream ---------------------------------------------------------------------
    def tasks(self, split: str = "all") -> list[str]:
        return list(self._order)

    def domain_of(self, task_id: str) -> str:
        return self._tasks[task_id].repo.replace("/", "__")

    def task_prompt(self, task_id: str) -> str:
        return codex_run.task_prompt(self._tasks[task_id], swe.PYTHON)

    def task_files(self, task_id: str) -> Path | None:
        return None  # the repository is large; editors see the task and trajectories

    def base_harness(self) -> Path:
        return self.root / "base"

    def validate_tree(self, tree: dict[str, str]) -> None:
        return None

    # -- execution -----------------------------------------------------------------------
    def execute(self, task_id: str, harness_dir: Path | None, run_id: str, *, timeout: int | None = None) -> Path:
        run_dir = self.spec.runs_root / run_id
        if (run_dir / "done.json").is_file():
            return run_dir
        run_dir.mkdir(parents=True, exist_ok=True)
        task = self._tasks[task_id]
        wd = swe.checkout(task)
        try:
            src = Path(harness_dir or self.base_harness())
            for entry in CODEX_ROOT_ENTRIES:
                p = src / entry
                if p.is_dir():
                    shutil.copytree(p, wd / entry, dirs_exist_ok=True)
                elif p.is_file():
                    shutil.copy2(p, wd / entry)
            if codex_run.AGENT == "claude":
                _to_claude_layout(wd)
            # Commit the harness so the patch only holds the agent's change.
            swe._git("add", "-A", cwd=wd)
            swe._git("-c", "user.name=h", "-c", "user.email=h@local", "commit", "-q", "-m", "harness", cwd=wd)
            usage = codex_run.run(wd, self.task_prompt(task_id), run_dir / "codex", timeout=timeout or 1800)
            patch = swe.diff(wd)
            (run_dir / "patch.diff").write_text(patch)
            hidden = swe.score(task, wd)
        finally:
            swe.remove(wd)
        self.scores_dir.mkdir(parents=True, exist_ok=True)
        (self.scores_dir / f"{run_id.replace('/', '__')}.json").write_text(
            json.dumps({"task": task_id, "run_id": run_id, **usage, **hidden}, indent=1))
        (run_dir / "done.json").write_text(json.dumps({"exit": usage["exit"], "wall_s": usage["wall_s"]}))
        return run_dir

    def delivered(self, run_dir: Path) -> bool:
        p = Path(run_dir) / "patch.diff"
        return p.is_file() and bool(p.read_text().strip())

    def trajectory(self, run_dir: Path, *, obs_trunc: int) -> str:
        out = []
        events = Path(run_dir) / "codex" / "events.jsonl"
        for line in events.read_text().splitlines() if events.is_file() else []:
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            item = ev.get("item", {})
            if ev.get("type") != "item.completed":
                continue
            if item.get("type") == "command_execution":
                out.append(f"[ACTION] {item.get('command', '')}\n"
                           f"[OBSERVATION] (exit {item.get('exit_code')})\n"
                           f"{str(item.get('aggregated_output', ''))[:4000]}")
            elif item.get("type") == "file_change":
                out.append(f"[ACTION] edit {json.dumps(item.get('changes', []))[:2000]}")
            elif item.get("type") in ("agent_message", "reasoning"):
                out.append(f"[ACTION] say: {str(item.get('text', ''))[:2000]}")
            elif item.get("type") == "error":
                out.append(f"[ERROR] {item.get('message', '')}")
        text = "\n\n".join(out)
        return text[-obs_trunc:] if len(text) > obs_trunc else text

    def deliverable_text(self, run_dir: Path) -> str:
        p = Path(run_dir) / "patch.diff"
        return p.read_text() if p.is_file() else ""

    def deliverable_files(self, run_dir: Path) -> dict[str, str]:
        return {"patch.diff": self.deliverable_text(run_dir)}
