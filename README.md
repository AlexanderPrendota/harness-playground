# harness-playground

Compares two recursive self-improvement methods on the same benchmark, with the same coding agent:

- **[Dream-RSI](https://github.com/google-research/dream-rsi)** (`8ec35bd`) learns the *exploration policy* around a fixed agent: how to spend a budget of attempts. Signal: a numeric evaluator, plus offline replay over recorded attempts.
- **[Harness²](https://github.com/google-research/harness2)** (`6868817`) learns the agent's *harness* (prompt, guardrails, skills, ...). Signal: contrasts between its own executions, with no ground truth.

Both are pinned as submodules under `vendor/`.

## Setup

| Role | Dream-RSI | Harness² |
|---|---|---|
| Solver (does the task) | Codex CLI, `gpt-6-luna` | Codex CLI, `gpt-6-luna` |
| Improver (rewrites policy / harness, selects) | Codex CLI, `gpt-6-luna` | Codex CLI, `gpt-6-luna` |

Same model for solving and improving in both arms, so differences come from the method. Harness² ships OpenCode and Claude CLI improver channels only. `adapters/harness2_swe.py:CodexProposer` swaps that one CLI call for `codex exec` and keeps the rest of the proposer (retries, cache, audit, harvest).

All Codex calls go through `agents/codex-shim`, which:
- uses an isolated `CODEX_HOME` (no user hooks or config);
- maps `--full-auto` (removed in Codex 0.169, still passed by Dream-RSI) to `-s workspace-write`;
- closes stdin, because `codex exec` blocks on a non-TTY stdin.

**Leakage controls.** The agent's workspace is a snapshot of `base_commit` with a fresh one-commit git history, because upstream history contains the actual fix. Hidden tests are applied only at scoring time, on a scratch copy. The Codex sandbox blocks the network.

## Benchmark: SWE-rebench slice

8 tasks from [`nebius/SWE-rebench-leaderboard`](https://huggingface.co/datasets/nebius/SWE-rebench-leaderboard), all from `tobymao/sqlglot` (issues from Nov 2025 – Apr 2026, SQL dialect parsing bugs).

- **Fresh** tasks reduce the risk of training-data contamination.
- **One repository = one domain**, so the Harness² experience library can transfer between tasks.
- **Hidden tests** give Dream-RSI a numeric evaluator and give the final measurement for both methods. Harness² never sees them.
- **Graded score:** the fraction of `FAIL_TO_PASS` tests that pass, gated on all `PASS_TO_PASS` tests passing.

`bench/validate.py` keeps only tasks where `FAIL_TO_PASS` fails at `base_commit` and everything passes with the gold patch. It runs on macOS without Docker: sqlglot is pure Python, so the tests run in a shared uv venv.

```bash
uv venv --python 3.13 .venv-tests
uv pip install --python .venv-tests/bin/python pytest pytz duckdb numpy pandas
git clone https://github.com/tobymao/sqlglot /tmp/hp-data/sqlglot
.venv-tests/bin/python bench/validate.py       # -> bench/tasks.jsonl
```

## Plan

- [x] Task slice + local validator (`bench/`)
- [x] Single-run baseline (`arms/single.py`)
- [x] Dream-RSI task wrapper (`adapters/dream_rsi_swe/`): the program is a list of `(file, old, new)` edits; the evaluator applies them to a clean snapshot and runs the hidden tests. The vendor launch scripts are used unchanged via symlinks plus a `common.sh` that only adds SWE task selection.
- [x] Harness² `BenchmarkAdapter` (`adapters/harness2_swe.py`): Codex harness layout, our own `codex exec` executor, delivered artifact = the git diff
- [x] Runs: Dream-RSI (`arms/dream_arm.sh`) and Harness² (`arms/harness2_arm.py --k 2`), 8 Codex rollouts per task each
- [x] `compare.py`: results table

## macOS notes

- Dream-RSI scripts need bash ≥ 4 (`brew install bash`).
- Harness²'s bundled Codex substrate targets a configured Responses endpoint. Here the adapter runs `codex exec` itself and reuses only the Codex harness layout.
