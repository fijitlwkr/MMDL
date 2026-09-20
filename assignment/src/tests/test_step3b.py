import json
from pathlib import Path
import subprocess
import sys

import pytest
import yaml

import common
from gate_env_check import failures
from validate_raw import validate


SOURCE = Path(__file__).resolve().parents[1]


def test_gate_fatal_sections_and_package_checks():
    report = {"sections": {
        "vllm_import": [{"name": "import", "status": "FAIL"}],
        "packages": [{"name": "pip_check", "status": "FAIL"},
                     {"name": "expected_version", "status": "FAIL"}],
        "gpu": [{"name": "available", "status": "SKIP"}],
    }}
    assert failures(report) == ["vllm_import.import", "packages.expected_version"]


def test_gate_cli(tmp_path):
    path = tmp_path / "env_check.json"
    path.write_text(json.dumps({"sections": {"model": [{"name": "x", "status": "FAIL"}]}}))
    result = subprocess.run([sys.executable, str(SOURCE / "gate_env_check.py"), str(path)],
                            capture_output=True, text=True)
    assert result.returncode == 1 and "model.x" in result.stdout


def record(identifier, cfg, subject="Accounting", status="ok"):
    sample = common.Sample(identifier, subject, None, None, None, "open", "Q", [], "[]", "A", [])
    return common.make_record(sample, cfg, synthetic=True,
                              status=status, reason="x" if status == "skip" else None,
                              error="bad" if status == "error" else None,
                              precomputed_prompt_tokens=1 if status == "ok" else None,
                              num_prompt_tokens=1 if status == "ok" else None,
                              raw_text="x" if status == "ok" else None,
                              output_token_ids=[1] if status == "ok" else None,
                              output_tokens=1 if status == "ok" else None,
                              finish_reason="stop" if status == "ok" else None)


def test_validate_raw_status_and_damage(tmp_path):
    cfg = yaml.safe_load((SOURCE / "config.yaml").read_text())
    cfg["dataset"]["expected_total_rows"] = 2
    cfg["dataset"]["subjects"] = ["Accounting"]
    cfg["dataset"]["expected_rows_per_subject"] = 2
    path = tmp_path / "raw.jsonl"
    path.write_text("\n".join(json.dumps(item) for item in [record("a", cfg), record("b", cfg, status="skip")]) + "\n")
    code, summary = validate(path, cfg, 2)
    assert code == 2 and summary["skip"] == 1
    path.write_text(path.read_text() + "{broken")
    code, summary = validate(path, cfg, 2)
    assert code == 1 and summary["errors"]


def test_runner_failure_records_stage(tmp_path):
    result = subprocess.run([str(SOURCE / "run_generate.sh"), "--out", str(tmp_path / "bad"),
                             "--skip_env_gate", "--model_path", str(tmp_path / "missing")],
                            cwd=SOURCE, capture_output=True, text=True)
    assert result.returncode != 0
    failed = tmp_path / "bad" / "logs" / "FAILED"
    assert failed.exists() and "stage=" in failed.read_text()


def test_runner_missing_hf_exits_four(tmp_path):
    result = subprocess.run([str(SOURCE / "run_generate.sh"), "--out", str(tmp_path / "no-hf")],
                            env={key: value for key, value in __import__("os").environ.items() if key != "HF_HOME"},
                            capture_output=True, text=True)
    assert result.returncode == 4
    assert "export HF_HOME=..." in result.stdout
    assert "stage=environment export" in (tmp_path / "no-hf/logs/FAILED").read_text()


def test_runner_missing_hf_directory_is_created(tmp_path):
    cache = Path("/tmp/preflight-cache")
    if not cache.exists():
        pytest.skip("preflight cache unavailable")
    hf = tmp_path / "new-hf"
    out = tmp_path / "new-out"
    result = subprocess.run([str(SOURCE / "run_generate.sh"), "--skip_env_gate", "--model_path",
                             str(tmp_path / "missing-model"), "--data_root", str(cache), "--out", str(out),
                             "--subjects", "Math", "--limit", "1"],
                            env={**__import__("os").environ, "HF_HOME": str(hf),
                                 "HF_HUB_OFFLINE": "1", "HF_DATASETS_OFFLINE": "1"},
                            capture_output=True, text=True)
    assert result.returncode != 0 and hf.is_dir()
    assert "stage=generation" in (out / "logs/FAILED").read_text()


def test_runner_disk_gate_exit_five(tmp_path):
    config = yaml.safe_load((SOURCE / "config.yaml").read_text())
    config["run"]["min_free_disk_gb"] = 999999
    config_path = tmp_path / "high.yaml"
    config_path.write_text(yaml.safe_dump(config, sort_keys=False))
    hf = tmp_path / "hf"
    result = subprocess.run([str(SOURCE / "run_generate.sh"), "--skip_env_gate", "--config",
                             str(config_path), "--out", str(tmp_path / "disk")],
                            env={**__import__("os").environ, "HF_HOME": str(hf)},
                            capture_output=True, text=True)
    assert result.returncode == 5 and "insufficient free disk space" in result.stdout


def test_empty_requirements_install_fails(tmp_path):
    # The repository requirements file is nonempty; exercise the same branch with
    # an isolated temporary script directory and a copied empty requirements file.
    script = tmp_path / "run.sh"
    script.write_text((SOURCE / "run_generate.sh").read_text().replace(
        'SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"',
        f'SCRIPT_DIR="{tmp_path}"'))
    script.chmod(0o755)
    (tmp_path / "requirements.txt").write_text("")
    (tmp_path / "config.yaml").write_text((SOURCE / "config.yaml").read_text())
    result = subprocess.run([str(script), "--out", str(tmp_path / "out"), "--install"],
                            capture_output=True, text=True)
    assert result.returncode == 3
    assert "requirements.txt is empty" in (tmp_path / "out/logs/01_install.log").read_text()


def test_runner_hardening_contract():
    source = (SOURCE / "run_generate.sh").read_text()
    assert source.index('if (( INSTALL )); then') < source.index('STAGE="environment export"')
    assert 'exit 4' in source and 'export HF_HOME=...' in source
    assert 'externally-managed-environment' in source and '--break-system-packages' in source
    assert 'import hf_transfer' in source and 'HF_HUB_ENABLE_HF_TRANSFER=1' in source
    assert 'min_free_disk_gb' in source and 'exit 5' in source
    assert 'stop command: runpodctl stop pod' in source
