#!/usr/bin/env bash
set -euo pipefail
if [[ $# -ne 2 ]]; then
  echo "Usage: setup_test_generation.sh CODE_DIR NEW_RECORDS_DIR" >&2
  exit 2
fi
SCRIPT_DIR=$(realpath "$1")
OUT=$(realpath -m "$2")
mkdir "$OUT"
mkdir "$OUT/logs"
export SCRIPT_DIR OUT INSTALL=1
python - <<'PY'
from importlib.metadata import version
from pathlib import Path
import os
import torch
assert version("torch") == torch.__version__ == "2.8.0+cu128"
text = (Path(os.environ["SCRIPT_DIR"]) / "run_generate.sh").read_bytes()
start = text.index(b"if (( INSTALL )); then\n")
end = text.index(b"python -m pip freeze", start)
(Path(os.environ["OUT"]) / "install_block.sh").write_bytes(text[start:end])
PY
python -m pip install --dry-run --break-system-packages --report "$OUT/install_plan.json" \
  -r "$SCRIPT_DIR/requirements.txt" > "$OUT/install_plan.log" 2>&1
python - "$OUT/install_plan.json" <<'PY'
import json
from pathlib import Path
import sys
plans = json.loads(Path(sys.argv[1]).read_bytes())["install"]
assert "torch" not in {item["metadata"]["name"].lower() for item in plans}, "Torch replacement planned"
PY
bash -euo pipefail "$OUT/install_block.sh"
python - <<'PY'
from importlib.metadata import version
import torch
assert version("torch") == torch.__version__ == "2.8.0+cu128"
assert version("vllm") == "0.11.0"
print(version("torch"), torch.__version__, version("vllm"))
PY
python -m pip check | tee "$OUT/pip_check.txt"
python -m pip freeze > "$OUT/packages.txt"
