#!/usr/bin/env bash
# One-time setup: submodules, three Python envs, the sqlglot mirror, an isolated Codex home,
# and validation of the task slice. Needs: git, uv, Node.js (for Codex CLI), bash >= 4.
set -euo pipefail
cd "$(dirname "$0")"

[ "${BASH_VERSINFO[0]}" -ge 4 ] || { echo "bash >= 4 required (macOS: brew install bash; run: bash setup.sh)"; exit 1; }
command -v uv >/dev/null || { echo "uv required: https://docs.astral.sh/uv/"; exit 1; }
command -v codex >/dev/null || npm i -g @openai/codex
[ -f "$HOME/.codex/auth.json" ] || { echo "Log in to Codex first: codex login"; exit 1; }

git submodule update --init

uv venv -q --allow-existing --python 3.13 .venv-tests
uv pip install -q --python .venv-tests/bin/python pytest pytz duckdb numpy pandas
uv venv -q --allow-existing --python 3.12 .venv-dream
uv pip install -q --python .venv-dream/bin/python -e vendor/dream-rsi
uv venv -q --allow-existing --python 3.12 .venv-h2
uv pip install -q --python .venv-h2/bin/python -e vendor/harness2

[ -d data/sqlglot ] || git clone -q https://github.com/tobymao/sqlglot data/sqlglot

# Isolated Codex home: same login, none of the user's config or hooks.
mkdir -p runs/codex-home
ln -sf "$HOME/.codex/auth.json" runs/codex-home/auth.json
printf 'model = "gpt-6-luna"\nmodel_reasoning_effort = "medium"\n' > runs/codex-home/config.toml

.venv-tests/bin/python bench/validate.py
echo "Setup done. Next: bash run.sh"
