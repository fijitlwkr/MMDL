#!/usr/bin/env bash
# Generation uses the image Python, as in the baseline main runner.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../../../.." && pwd)"
case "$ROOT" in /workspace/*) ;; *) echo "Checkout must be under /workspace" >&2; exit 2;; esac
export HF_HOME=/workspace/hf_cache
export XDG_CACHE_HOME=/workspace/cache PIP_CACHE_DIR=/workspace/pip_cache TMPDIR=/workspace/tmp
mkdir -p "$HF_HOME" "$XDG_CACHE_HOME" "$PIP_CACHE_DIR" "$TMPDIR"
python3.12 -c 'import sys; assert sys.version_info[:3] == (3,12,3), sys.version'
nvidia-smi --query-gpu=name --format=csv,noheader | grep -F 'RTX 4090'
python3.12 - <<'PY'
import importlib.metadata as m, subprocess, sys, torch
from pathlib import Path
print(m.version('torch'), torch.__version__)
assert m.version('torch') == torch.__version__ == '2.8.0+cu128'
assert Path(subprocess.check_output(['python','-c','import sys; print(sys.executable)'],text=True).strip()).resolve() == Path(sys.executable).resolve()
PY
# Preserve main code/run_generate.sh's default PEP 668 handling as well.
INSTALL_LOG="$(mktemp "$TMPDIR/hypB-install.XXXXXX.log")"
set +e
python -m pip install -r "$ROOT/code/requirements.txt" 2>&1 | tee "$INSTALL_LOG"
INSTALL_CODE=${PIPESTATUS[0]}
set -e
if (( INSTALL_CODE != 0 )); then
    if grep -qi "externally-managed-environment" "$INSTALL_LOG"; then
        python -m pip install --break-system-packages -r "$ROOT/code/requirements.txt" 2>&1 | tee -a "$INSTALL_LOG"
    else
        exit "$INSTALL_CODE"
    fi
fi
python3.12 - <<'PY'
import importlib.metadata as m, importlib.util, torch
print(m.version('torch'), torch.__version__)
assert m.version('torch') == torch.__version__ == '2.8.0+cu128'
assert importlib.util.find_spec('peft') is None, 'PEFT must remain confined to the merge environment'
PY
python -m pip check
python3.12 "$HERE/verify_code.py"
# Existing venv is for merging only; never put it on the generation PATH.
test -x /workspace/hypB-eval-env/bin/python
/workspace/hypB-eval-env/bin/python -c 'import importlib.metadata as m; assert m.version("peft") == "0.17.1"'
