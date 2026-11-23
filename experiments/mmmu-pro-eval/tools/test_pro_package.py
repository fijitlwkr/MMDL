"""Pro 패키지 CPU 점검: 가짜 MMMU-Pro 데이터로 로더·raw 검사·채점 경로를 확인한다. 네트워크·GPU 없음.

사용: python -I test_pro_package.py <빌드된 패키지 폴더>
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import types

import pyarrow as pa
import yaml

PKG = Path(sys.argv[1]).resolve()
CODE = PKG / "code"


def ids_digest(ids):
    return hashlib.sha256("\n".join(sorted(ids)).encode("utf-8")).hexdigest()


class FakeDataset:
    def __init__(self, rows):
        self.rows = rows
        self.column_names = list(rows[0])
        self.data = types.SimpleNamespace(column=lambda name: pa.array([r[name] for r in self.rows]))

    def __len__(self):
        return len(self.rows)

    def __getitem__(self, index):
        return self.rows[index]

    def remove_columns(self, names):
        return FakeDataset([{k: v for k, v in r.items() if k not in names} for r in self.rows])


ROWS = [
    {"id": "test_History_1", "subject": "History", "question": "Q1 <image 1>", "options": str([f"o{i}" for i in range(10)]),
     "answer": "J", "img_type": "['Photos']", "topic_difficulty": "Easy", "explanation": "",
     "image_1": "IMG", "image_2": None},
    {"id": "validation_Art_3", "subject": "Art", "question": "Q2", "options": str([f"p{i}" for i in range(10)]),
     "answer": "C", "img_type": "['Paintings']", "topic_difficulty": "Hard", "explanation": "",
     "image_1": "IMG", "image_2": "IMG"},
    {"id": "test_History_7", "subject": "History", "question": "Q3", "options": str([f"q{i}" for i in range(10)]),
     "answer": "A", "img_type": "['Maps']", "topic_difficulty": "Medium", "explanation": "",
     "image_1": "IMG", "image_2": None},
]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def main():
    cfg = yaml.safe_load((CODE / "config_pro.yaml").read_text(encoding="utf-8"))
    test_cfg = yaml.safe_load((CODE / "config_test.yaml").read_text(encoding="utf-8"))
    for key in set(cfg) | set(test_cfg):
        if key != "dataset":
            assert cfg[key] == test_cfg[key], f"config section changed: {key}"
    print("config: 생성·이미지·채점 설정이 config_test.yaml과 같음")

    fake_cfg = json.loads(json.dumps(cfg))
    fake_cfg["dataset"].update(expected_rows_by_subject={"Art": 1, "History": 2}, expected_total_rows=3,
                               subjects=["Art", "History"], expected_ids_sha256=ids_digest([r["id"] for r in ROWS]))
    calls = []

    def fake_load_dataset(repo, name, split, revision, cache_dir):
        calls.append((repo, name, split, revision))
        return FakeDataset(ROWS)

    sys.modules["datasets"] = types.SimpleNamespace(load_dataset=fake_load_dataset)
    sys.path.insert(0, str(CODE))
    common = load("common", CODE / "common.py")
    samples = common.load_samples(fake_cfg, None)
    assert calls == [("MMMU/MMMU_Pro", "standard (10 options)", "test", fake_cfg["dataset"]["revision"])]
    assert [s.id for s in samples] == ["validation_Art_3", "test_History_1", "test_History_7"]
    assert all(s.question_type == "multiple-choice" and len(s.options) == 10 for s in samples)
    assert samples[0].image_indices == [1, 2] and samples[1].image_indices == [1]
    prompt = common.build_prompt(samples[1], fake_cfg)
    assert prompt.startswith("Question: Q1 <image 1>\nOptions:\nA. o0\n") and "J. o9\n" in prompt
    assert prompt.endswith("Please select the correct answer from the options above.")
    print("loader: 과목 순서·이미지 번호·10지선다 프롬프트 OK")

    bad = json.loads(json.dumps(fake_cfg)); bad["dataset"]["expected_ids_sha256"] = "0" * 64
    try:
        common.load_samples(bad, None); raise AssertionError("ID hash mismatch not caught")
    except ValueError:
        pass
    print("loader: ID 해시 불일치 차단 OK")

    evaluate = load("evaluate", CODE / "scoring" / "evaluate.py")
    raws = []
    for s, text in zip(samples, ["Final Answer: C", "The answer is J.", "I think it is A"]):
        rec = common.make_record(s, fake_cfg, status="ok", raw_text=text, output_token_ids=[1, 2],
                                 output_tokens=2, finish_reason="stop", num_prompt_tokens=10,
                                 precomputed_prompt_tokens=10)
        raws.append(rec)
    assert evaluate.validate_raw(raws, fake_cfg["dataset"]) == []
    parsers = evaluate.load_parsers()
    items = [evaluate.derive_item(r, parsers) for r in raws]
    print("routes:", [(i["id"], i["route"], i["auto_answer"], i["gt"]) for i in items])
    assert items[0]["auto_answer"] == "C"
    # Qwen 규칙이 못 잡는 응답(A·B·J 여러 글자 언급)에서 Final Answer: J를 보완 규칙이 잡는지
    text = "Options A and B are wrong because of the scale.\nFinal Answer: J"
    choices = {chr(65 + i): f"o{i}" for i in range(10)}
    assert parsers.qwen_parse(text, choices) is None
    assert parsers.marker(text, choices)["answer"] == "J"
    # 선택지 9개 이하에서는 J를 받지 않는다(MMMU 결과 불변)
    assert parsers.marker("Final Answer: J", {chr(65 + i): "x" for i in range(9)})["answer"] is None
    print("parsers: Final Answer J 보완 OK, 9지 이하 불변 OK")
    tampered = [dict(raws[0], id="test_History_99")] + raws[1:]
    try:
        evaluate.validate_raw(tampered, fake_cfg["dataset"]); raise AssertionError("raw ID set mismatch not caught")
    except ValueError:
        pass
    print("evaluate: Pro ID 검사·10지선다 채점 경로 OK")

    src = (CODE / "metadata.py").read_text(encoding="utf-8")
    assert "MMMU/MMMU_Pro" in src and "98e6ac0cb9b7b2cd2c991b85a50762edc4aedc68" in src
    print("ALL OK")


if __name__ == "__main__":
    main()
