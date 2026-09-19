import copy
import json
from pathlib import Path
import subprocess
import sys

import pytest
import yaml
from datasets import Dataset


from assignment.src import common, generate


@pytest.fixture
def cfg():
    return yaml.safe_load((Path(__file__).resolve().parents[1] / "config.yaml").read_text())


def sample(index=0, *, kind="multiple-choice", options=None, question=None, images=None):
    options = ["one", "two"] if options is None else options
    return common.Sample(id=f"test_{index}", subject="Test", subfield=None, topic_difficulty=None,
                         img_type=None, question_type=kind, question=question or "Choose",
                         options=options, options_raw=repr(options), answer="A" if kind != "open" else "free",
                         image_indices=images or [])


@pytest.mark.parametrize("count", [2, 3, 4, 5])
def test_prompt_option_letters_and_open(cfg, count):
    item = sample(options=[str(index) for index in range(count)])
    prompt = common.build_prompt(item, cfg)
    assert prompt.startswith("Question: Choose\nOptions:\n")
    assert all(f"{chr(65 + index)}. {index}" in prompt for index in range(count))
    assert prompt.endswith("Please select the correct answer from the options above.")
    open_prompt = common.build_prompt(sample(kind="open", options=[]), cfg)
    assert open_prompt == "Question: Choose"


def test_markers_and_message_image_order(cfg):
    item = sample(options=["<image 2>", "text"], question="See <image 1>", images=[2, 1])
    prompt = common.build_prompt(item, cfg)
    assert "<image 1>" in prompt and "<image 2>" in prompt
    messages = common.build_messages(item, cfg, {2: "second", 1: "first"})
    assert [part["image"] for part in messages[0]["content"][:-1]] == ["first", "second"]
    assert messages[0]["content"][-1]["text"] == prompt


def test_load_samples_order_and_options_failure(monkeypatch, cfg):
    cfg = copy.deepcopy(cfg)
    cfg["dataset"]["subjects"] = ["A", "B"]
    cfg["dataset"]["expected_rows_per_subject"] = 1
    cfg["dataset"]["expected_total_rows"] = 2
    def load_dataset(repo, subject, **kwargs):
        return Dataset.from_dict({"id": [subject], "question": ["Q"], "options": ["['x', 'y']"],
                                  "answer": ["A"], "question_type": ["multiple-choice"],
                                  "image_1": ["placeholder"], "image_2": [None]})
    monkeypatch.setattr("datasets.load_dataset", load_dataset)
    items = common.load_samples(cfg, None, ["B", "A"])
    assert [item.id for item in items] == ["A", "B"]
    assert items[0].image_indices == [1]
    def bad_dataset(repo, subject, **kwargs):
        return Dataset.from_dict({"id": [subject], "question": ["Q"], "options": ["invalid ["],
                                  "answer": ["A"], "question_type": ["multiple-choice"]})
    monkeypatch.setattr("datasets.load_dataset", bad_dataset)
    with pytest.raises(SyntaxError):
        common.load_samples(cfg, None, ["A"])


def test_schema_four_statuses_and_rejections(cfg):
    item = sample()
    base = common.make_record(item, cfg, synthetic=True, precomputed_prompt_tokens=3)
    records = [
        base | {"status": "ok", "raw_text": " A ", "output_token_ids": [1], "output_tokens": 1,
                "finish_reason": "stop", "num_prompt_tokens": 3},
        base | {"status": "ok", "raw_text": " B ", "output_token_ids": [1] * cfg["budget"]["max_new_tokens"],
                "output_tokens": cfg["budget"]["max_new_tokens"], "finish_reason": "length", "num_prompt_tokens": 3},
        base | {"status": "skip", "reason": "prompt_too_long"},
        base | {"status": "error", "error": "RuntimeError('bad')"},
    ]
    for record in records:
        common.validate_record(record)
        assert not common.check_invariants(record)
    for invalid in (dict(list(records[0].items())[1:]), records[0] | {"extra": 1},
                    records[0] | {"synthetic": 1}, records[0] | {"options": [1]},
                    records[0] | {"output_token_ids": [True]}):
        with pytest.raises((ValueError, TypeError)):
            common.validate_record(invalid)


def test_invariant_violations(cfg):
    base = common.make_record(sample(), cfg)
    cases = [
        (base | {"status": "ok", "output_token_ids": [1], "output_tokens": 2}, "output_token_count"),
        (base | {"status": "ok", "output_token_ids": [1], "output_tokens": 1,
                 "finish_reason": "length"}, "length_token_count"),
        (base | {"status": "skip", "reason": "prompt_too_long", "raw_text": "bad"}, "skip_output_not_null"),
        (base | {"status": "skip"}, "skip_reason_missing"),
        (base | {"status": "error"}, "error_missing"),
    ]
    for record, name in cases:
        assert name in common.check_invariants(record)


def test_smoke_selection_deterministic():
    items = [sample(0), sample(1, kind="open", options=[]), sample(2, images=[1, 2, 3, 4]),
             sample(3, images=[1, 2]), sample(4, options=["<image 1>", "x"]), sample(5)]
    expected = ["test_1", "test_2", "test_3", "test_4", "test_0"]
    assert [item.id for item in common.select_smoke(items, 5)] == expected
    assert [item.id for item in common.select_smoke(items, 5)] == expected


def run(cfg, out, items, engine=None, config_bytes=b"same"):
    return generate.run_pipeline(cfg, config_bytes, out, items, "model", "revision", None, True,
                                 engine=engine, counter=generate.FakeTokenCounter())


def read_raw(out, cfg):
    return [json.loads(line) for line in (out / cfg["run"]["raw_filename"]).read_text().splitlines()]


def test_resume_interruption_matches_uninterrupted_and_skips_engine(tmp_path, cfg):
    cfg = copy.deepcopy(cfg)
    cfg["run"]["chunk_size"] = 2
    items = [sample(index) for index in range(6)]
    full = tmp_path / "full"
    interrupted = tmp_path / "interrupted"
    full_engine = generate.FakeEngine()
    assert run(cfg, full, items, full_engine) == 2
    assert items[2].id not in [id for call in full_engine.calls for id in call]
    assert read_raw(full, cfg)[2]["image_indices"] == []
    with pytest.raises(RuntimeError, match="interruption"):
        run(cfg, interrupted, items, generate.FakeEngine(stop_after_chunks=1))
    assert len(read_raw(interrupted, cfg)) == 2
    assert run(cfg, interrupted, items, generate.FakeEngine()) == 2
    assert read_raw(interrupted, cfg) == read_raw(full, cfg)
    before = (interrupted / cfg["run"]["raw_filename"]).read_bytes()
    assert run(cfg, interrupted, items, generate.FakeEngine()) == 2
    assert (interrupted / cfg["run"]["raw_filename"]).read_bytes() == before


def test_recover_torn_and_resume_rejections(tmp_path, cfg):
    items = [sample(index) for index in range(5)]
    out = tmp_path / "case"
    assert run(cfg, out, items) == 2
    raw = out / cfg["run"]["raw_filename"]
    lines = raw.read_bytes().splitlines(keepends=True)
    raw.write_bytes(b"".join(lines[:-1]) + b'{"broken":')
    assert run(cfg, out, items) == 2
    assert (out / (cfg["run"]["raw_filename"] + ".torn")).read_bytes() == b'{"broken":'
    assert len(read_raw(out, cfg)) == 5
    with pytest.raises(ValueError, match="config_sha256"):
        run(cfg, out, items, config_bytes=b"changed")
    env_path = out / cfg["run"]["env_filename"]
    env = json.loads(env_path.read_text())
    env["dry_run"] = False
    env_path.write_text(json.dumps(env))
    with pytest.raises(ValueError, match="dry_run"):
        run(cfg, out, items)


def test_resume_rejects_foreign_and_duplicate_ids(tmp_path, cfg):
    items = [sample(index) for index in range(4)]
    out = tmp_path / "case"
    run(cfg, out, items)
    raw = out / cfg["run"]["raw_filename"]
    original = raw.read_text()
    raw.write_text(original + original.splitlines()[0] + "\n")
    with pytest.raises(ValueError, match="duplicate id"):
        run(cfg, out, items)
    foreign = json.loads(original.splitlines()[0])
    foreign["id"] = "foreign"
    raw.write_text(original + json.dumps(foreign) + "\n")
    with pytest.raises(ValueError, match="outside selection"):
        run(cfg, out, items)


def test_token_mismatch_discards_whole_chunk(tmp_path, cfg):
    cfg = copy.deepcopy(cfg)
    cfg["run"]["chunk_size"] = 2
    items = [sample(index) for index in range(6)]
    out = tmp_path / "case"
    with pytest.raises(AssertionError, match="mismatch"):
        run(cfg, out, items, generate.FakeEngine(mismatch_ordinal=4))
    assert [item["id"] for item in read_raw(out, cfg)] == [item.id for item in items[:4]]


def test_no_heavy_modules_on_dry_run_and_no_forbidden_source_strings(tmp_path, cfg):
    script = """
import sys
import yaml
from pathlib import Path
from assignment.src import common, generate
cfg = yaml.safe_load(Path('assignment/src/config.yaml').read_text())
item = common.Sample('id', 'subject', None, None, None, 'open', 'Question', [], '[]', 'answer', [])
generate.run_pipeline(cfg, b'config', Path(sys.argv[1]), [item], 'model', 'revision', None, True)
assert 'vllm' not in sys.modules and 'torch' not in sys.modules and 'transformers' not in sys.modules
"""
    completed = subprocess.run([sys.executable, "-c", script, str(tmp_path / "case")],
                               capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr
    source = Path(__file__).resolve().parents[1]
    for name in ("check_env.py", "common.py", "generate.py"):
        code = (source / name).read_text()
        assert not any(piece in code for piece in ("assignment", "results", "runs", "/workspace", "/home"))
