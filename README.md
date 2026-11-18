# harness-playground

Compares two recursive self-improvement methods on the same benchmark, with the same coding agent:

- **[Dream-RSI](https://github.com/google-research/dream-rsi)** (`8ec35bd`) learns the *exploration policy* around a fixed agent: how to spend a budget of attempts. Signal: a numeric evaluator, plus offline replay over recorded attempts.
- **[Harness²](https://github.com/google-research/harness2)** (`6868817`) learns the agent's *harness* (prompt, guardrails, skills, ...). Signal: contrasts between its own executions, with no ground truth.

Both are pinned as submodules under `vendor/` and run unmodified. Everything here is adapters, a benchmark slice and a comparison script.

## Quick start

```bash
codex login        # once, with a ChatGPT plan that includes Codex
bash setup.sh      # envs, submodules, sqlglot mirror, task validation (no agent calls)
bash run.sh        # all arms, then the results table (≈280 agent sessions)
bash run.sh compare   # only rebuild the table from existing runs
```

To run with Claude Code instead of Codex: `HP_AGENT=claude bash run.sh` (needs `claude` logged in).

Requirements: git, [uv](https://docs.astral.sh/uv/), Node.js, bash ≥ 4 (macOS: `brew install bash`). Docker is not needed.

## Experiment protocol

The same model solves the tasks and drives the improvement in every arm, so differences come from the method. All arms are scored on hidden tests, applied after the run.

| Arm | Agent rollouts per task | How the answer is chosen | Code |
|---|---|---|---|
| Single run | 1 | – | `arms/single.py` |
| Plain best-of-3 | 3 (single run + the 2 Harness² base runs) | Hidden tests | computed in `compare.py` |
| Dream-RSI | 8: shared first round E0 (2 branches × 2 attempts), then one round with the learned policy vs. one with the fixed policy (the paper's RFE baseline) | Hidden tests (its evaluator) | `arms/dream_arm.sh` |
| Harness², parallel mode, k=2 | 8: 2 base, 4 edited probes, 2 composed finals; the experience library carries across tasks | Blind LLM selection | `arms/harness2_arm.py` |

Columns printed by `compare.py`:

| Column | Meaning |
|---|---|
| `single` | Score of the single run |
| `best3 (plain)` | Best of the single run and the 2 Harness² base runs |
| `DR-E0 (4)` | Best of Dream-RSI's shared first round |
| `DR-fixed (8)`, `DR-learned` | Best over E0 + the fixed-policy / learned-policy round (rollouts in brackets) |
| `H2-base` | Mean score of the Harness² base runs |
| `H2 final (8)` | Score of the deliverable Harness² selected |
| `H2 best rollout` | Best of all 8 Harness² rollouts (oracle, for reference) |

## Benchmark: SWE-rebench slice

8 tasks from [`nebius/SWE-rebench-leaderboard`](https://huggingface.co/datasets/nebius/SWE-rebench-leaderboard), all from `tobymao/sqlglot` (SQL dialect parsing bugs, issues from Nov 2025 – Apr 2026).

- **One repository = one domain**, so the Harness² experience library can transfer between tasks.
- **Score** = fraction of `FAIL_TO_PASS` tests passing, or 0 if any `PASS_TO_PASS` test breaks. Every task in this slice has a single `FAIL_TO_PASS` test, so in practice the score is pass/fail.
- **Validation:** `bench/validate.py` keeps a task only if `FAIL_TO_PASS` fails at `base_commit` and everything passes with the gold patch. sqlglot is pure Python, so the tests run in one shared uv venv.

**Leakage controls.** The agent's workspace is a snapshot of `base_commit` with a fresh one-commit git history, because upstream history contains the actual fix. Hidden tests are applied only at scoring time, on a scratch copy. Codex runs in its `workspace-write` sandbox, where network access is off by default (not separately tested). Claude Code runs with the web tools disabled.

## Follow-up studies

Task lists in `bench/`, built from SWE-rebench and validated with `bench/validate.py --src ... --dst ...`:

| File | Contents |
|---|---|
| `sqlglot_all.jsonl` | All valid sqlglot tasks from the SWE-rebench leaderboard |
| `sqlglot_calib.jsonl` | The same minus the main slice; used to estimate single-run solve rates |
| `sqlglot_graded.jsonl` | sqlglot tasks with ≥ 5 `FAIL_TO_PASS` tests, from the full SWE-rebench dataset (2022–2024) |
| `study_library.jsonl` | 12 newer tasks a single run rarely solves |
| `study_dream.jsonl` | 6 multi-test tasks with a low starting score |

```bash
# solve-rate calibration: two single runs per task
python arms/single.py --tasks-file bench/sqlglot_calib.jsonl --out runs/calib/run1
python study_compare.py calib --tasks-file bench/sqlglot_calib.jsonl --runs runs/calib/run1 runs/calib/run2

# Harness² experience library: carried across tasks vs. reset before each task
python arms/harness2_arm.py --k 1 --tasks-file bench/study_library.jsonl --library carry --out runs/study-library/carry
python arms/harness2_arm.py --k 1 --tasks-file bench/study_library.jsonl --library reset --out runs/study-library/reset
python study_compare.py library --tasks-file bench/study_library.jsonl --carry runs/study-library/carry --reset runs/study-library/reset

# Dream-RSI learned vs. fixed policy on multi-test tasks, 3 rounds of 2x2
HP_TASKS_FILE=bench/study_dream.jsonl HP_DREAM_WS=$PWD/workspace/study-dream ROUNDS=3 bash arms/dream_arm.sh
python study_compare.py dream --tasks-file bench/study_dream.jsonl --ws workspace/study-dream
```

Use the venvs from `setup.sh`: `.venv-tests` for `single.py` and `study_compare.py`, `.venv-h2` for `harness2_arm.py`.

## Repository layout

| Path | Contents |
|---|---|
| `bench/` | Task slice (`tasks.jsonl`), loader, snapshot checkout, hidden-test scoring (`swe.py`), validator |
| `agents/codex_run.py` | Runs one agent rollout and records tokens, cost and wall time |
| `agents/codex-shim` | Single entry point for Codex: isolated `CODEX_HOME`, `--full-auto` mapped to `-s workspace-write` (removed in Codex 0.169, still passed by Dream-RSI), stdin closed |
| `agents/claude-shim` | Same `codex exec` interface on top of Claude Code (no user hooks, plugins or MCP) |
| `adapters/dream_rsi_swe/` | Turns a SWE task into a Dream-RSI task: the program is a list of `(file, old, new)` edits; the evaluator applies them to a clean snapshot and runs the hidden tests. `scripts/` symlinks the vendor launch scripts and adds SWE task selection in `common.sh` |
| `adapters/harness2_swe.py` | Harness² `BenchmarkAdapter`: Codex harness layout, our own rollout executor, delivered artifact = the git diff; `CodexProposer` runs the improver on the same agent |
| `arms/` | One entry point per arm |
| `compare.py` | Results table of the main comparison |
| `study_compare.py` | Tables for the follow-up studies |

Generated, not committed: `data/` (sqlglot mirror), `runs/` (single and Harness² runs, Codex home), `workspace/` (Dream-RSI workspaces). On a re-run, `single.py` starts over, Harness² skips finished tasks, and Dream-RSI refuses to overwrite an existing workspace. Delete `runs/` and `workspace/` for a clean re-run.

## Settings

| Variable | Default | Effect |
|---|---|---|
| `HP_AGENT` | `codex` | `claude` switches every arm to Claude Code; outputs go to `runs/claude/` and `workspace/claude/` |
| `HP_CLAUDE_MODEL` / `HP_CLAUDE_EFFORT` | `claude-sonnet-5-5` / `low` | Claude Code model and effort |
| `HP_CODEX_HOME` | `runs/codex-home` | Codex home used by the shim (model `gpt-6-luna`, effort medium) |
| `HP_MIRRORS` | `data/` | Where repository mirrors live |
| `HP_TASKS_FILE`, `HP_DREAM_WS` | `bench/tasks.jsonl`, `workspace/dream` | Task list and workspace root for `arms/dream_arm.sh`; `ROUNDS`, `BRANCHES`, `REFINE` set its budget |

## Adaptations and caveats

- **Harness² improver.** Harness² ships OpenCode and Claude CLI improver channels only. `CodexProposer` replaces that one CLI call with the selected agent and keeps the rest of the proposer (retries, cache, audit, harvest). Its token usage is not recorded.
- **Harness² on Claude Code.** The Codex harness layout is mapped onto Claude Code's at execution: AGENTS.md → CLAUDE.md, `.agents/skills` → `.claude/skills`, hooks → `.claude/settings.json`.
- **Repository instruction files.** The newest tasks ship their own AGENTS.md/CLAUDE.md. The Harness² harness replaces it; the other arms see the repository's file.
- **Dream-RSI all-zero rounds.** The vendor launch scripts reject a round where no attempt scored above 0, treating it as a broken setup. On SWE tasks it is a legitimate outcome, so `common.sh` accepts it if every attempt was evaluated.
- **Dream-RSI learning after the last round** runs as in the vendor pipeline but cannot affect the result.
- **Harness² on macOS.** Its bundled Codex substrate targets a configured Responses endpoint; the adapter runs the agent itself and reuses only the harness layout.
