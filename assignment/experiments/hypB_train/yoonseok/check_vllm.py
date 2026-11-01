"""Load a merged directory using the repository's actual evaluation engine."""
import argparse
from importlib.metadata import version
from pathlib import Path
import sys
import yaml

CODE = Path(__file__).resolve().parents[4] / "code"
sys.path.insert(0, str(CODE))
from vllm_engine import VLLMEngine


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("merged", type=Path)
    args = parser.parse_args()
    assert version("vllm") == "0.11.0" and (args.merged / "config.json").is_file()
    engine = VLLMEngine(yaml.safe_load((CODE / "config.yaml").read_text()), args.merged.resolve())
    print(f"vLLM 0.11.0 loaded {args.merged} in {engine.init_seconds}s")
