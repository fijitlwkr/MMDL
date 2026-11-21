"""Check held-out preference inputs on CPU and write their standalone report."""

from collections import Counter
import importlib.metadata
import json
import os
import random

from classify_answers import ROOT, WORKSPACE, read_rows, write_json
from check_dpo_pairs import END, PROCESSOR
from d3_pair_preference import category, encode_pair, make_template, self_test
from d3_prepare_dev_pairs import DEV_INDEX, DEV_PAIRS, PROBE, protected_hashes
from d3_report import table
from sample_m0 import CONFIG, example_for, load_processor, prompt_input, sha


def main():
    names = ("d3_dev_pairs_validation.json", "d3_pair_preference_tests.json", "D3_DEV_PAIRS_REPORT.md", "d3_dev_pairs_sha256.json")
    assert not any((ROOT / "reports" / name).exists() for name in (names[0], *names[2:])), "Preserve existing reports"
    before = protected_hashes()
    os.chdir(WORKSPACE)
    cache = ROOT / "data/d3p_cpu"
    cache.mkdir(exist_ok=True)
    os.environ.update(CUDA_VISIBLE_DEVICES="-1", HF_HUB_OFFLINE="1", HF_DATASETS_OFFLINE="1",
                      MODELSCOPE_OFFLINE="1", MODELSCOPE_CACHE=os.path.relpath(cache, WORKSPACE),
                      MIN_PIXELS="1003520", MAX_PIXELS="4014080", IMAGE_MIN_TOKEN_NUM="980",
                      IMAGE_MAX_TOKEN_NUM="3920", SPATIAL_MERGE_SIZE="2")
    import torch
    import yaml
    from swift.llm import get_model_tokenizer, load_dataset

    torch.set_num_threads(4)
    tests = self_test()
    test_path = ROOT / "reports/d3_pair_preference_tests.json"
    if test_path.exists():
        assert json.loads(test_path.read_bytes()) == tests
    else:
        write_json(test_path, tests)
    split = json.loads((ROOT / "data/d3_split.json").read_bytes())
    dev_rows = set(split["development_rows"])
    training = read_rows(ROOT / "data/d3_pairs_v2_index.jsonl")
    data, refs = read_rows(DEV_PAIRS), read_rows(DEV_INDEX)
    d1_data_lines = (ROOT / "data/d1_pairs_swift.jsonl").read_bytes().splitlines(keepends=True)
    d1_index_lines = (ROOT / "data/d1_pairs_index.jsonl").read_bytes().splitlines(keepends=True)
    expected = [n for n, line in enumerate(d1_index_lines) if json.loads(line)["row"] in dev_rows]
    assert len(data) == len(refs) == len(expected) == 146
    assert DEV_PAIRS.read_bytes() == b"".join(d1_data_lines[n] for n in expected)
    assert DEV_INDEX.read_bytes() == b"".join(d1_index_lines[n] for n in expected)
    assert not {ref["row"] for ref in refs} & {ref["row"] for ref in training}
    original_probe_lines = (ROOT / "data/d3_pairs_v2_index.jsonl").read_bytes().splitlines(keepends=True)
    assert PROBE.read_bytes() == b"".join(random.Random(3407).sample(original_probe_lines, 146))
    probe = read_rows(PROBE)
    assert len(probe) == len({ref["pair"] for ref in probe}) == 146
    pool = {item["row"]: item for item in read_rows(ROOT / "data/r1_pool.jsonl")}
    cfg = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    processor = load_processor(PROCESSOR.resolve(strict=True), cfg)
    lengths = []
    for ordinal, (example, ref) in enumerate(zip(data, refs, strict=True)):
        item = pool[ref["row"]]
        original = example_for(item, None)
        assert example["messages"][:-1] == original["messages"] and example["images"] == original["images"]
        assert example["rejected_add_eos"] is (False if category(ref) == "truncated" else None)
        chosen = len(processor.tokenizer.encode(example["messages"][-1]["content"] + END, add_special_tokens=False))
        rejected = len(processor.tokenizer.encode(example["rejected_response"] + ("" if example["rejected_add_eos"] is False else END), add_special_tokens=False))
        lengths.append({"ordinal": ordinal, "pair": ref["pair"], "row": ref["row"], "category": category(ref),
                        "prompt": item["prompt_tokens"], "chosen": chosen, "rejected": rejected,
                        "longest": item["prompt_tokens"] + max(chosen, rejected)})
    longest = max(lengths, key=lambda row: row["longest"])
    assert longest["longest"] <= 10240
    selected = {longest["ordinal"]}
    for reason in ("wrong", "truncated", "extract_fail"):
        selected.update(row["ordinal"] for row in [r for r in lengths if r["category"] == reason][:2])
    for ordinal in range(len(refs)):
        if len(selected) >= 7:
            break
        selected.add(ordinal)
    loaded, _ = load_dataset(str(DEV_PAIRS), strict=True, use_hf=True, shuffle=False, remove_unused_columns=False)
    model, swift_processor = get_model_tokenizer(str(PROCESSOR.resolve()), model_type="qwen3_vl", load_model=False, use_hf=True)
    assert model is None and importlib.metadata.version("ms-swift") == "3.12.3"
    template = make_template(swift_processor)
    checks = []

    def check_one(example, ref, name):
        item = pool[ref["row"]]
        prepared, prompt, _ = prompt_input(example_for(item, None), WORKSPACE, cfg, processor)
        for image in prepared["multi_modal_data"]["image"]:
            image.close()
        assert len(prompt) == item["prompt_tokens"]
        encoded = encode_pair(template, example)
        observation = {"dataset": name, "pair": ref["pair"], "row": ref["row"], "category": category(ref),
                       "prompt": len(prompt), "image_tokens": prompt.count(processor.image_token_id), "branches": {}}
        for branch in ("chosen", "rejected"):
            response = example["messages"][-1]["content"] if branch == "chosen" else example["rejected_response"]
            end = "" if branch == "rejected" and example["rejected_add_eos"] is False else END
            completion = processor.tokenizer.encode(response + end, add_special_tokens=False)
            assert encoded[branch + "_input_ids"] == prompt + completion
            assert encoded[branch + "_labels"] == [-100] * len(prompt) + completion
            observation["branches"][branch] = {"completion": len(completion), "full_ids_match": True, "labels_match": True,
                                                "eos_suffix_appended": bool(end)}
        checks.append(observation)
        print("PREFERENCE_CPU", name, ref["pair"], category(ref), "PASS", flush=True)

    for ordinal in sorted(selected):
        check_one(loaded[ordinal], refs[ordinal], "development")
    train_loaded, _ = load_dataset(str(ROOT / "data/d3_pairs_v2_swift.jsonl"), strict=True, use_hf=True,
                                   shuffle=False, remove_unused_columns=False)
    concise_probe = [ref for ref in probe if ref["kind"] == "concise"][:2]
    assert len(concise_probe) == 2
    for ref in concise_probe:
        assert training[ref["pair"]] == ref
        check_one(train_loaded[ref["pair"]], ref, "training_probe")
    assert len(checks) >= 5 and template.model is None and template.dummy_model is None
    assert protected_hashes() == before
    validation = {"status": "PASS", "development_pairs": len(refs), "development_questions": len({r["row"] for r in refs}),
                  "development_rows_byte_identical_to_d1": True, "d1_order_preserved": True, "training_question_overlap": 0,
                  "development_rejected_categories": Counter(category(ref) for ref in refs), "longest": longest,
                  "training_probe_pairs": len(probe), "training_probe_by_kind": Counter(ref["kind"] for ref in probe),
                  "training_probe_rejected_categories": Counter(category(ref) for ref in probe),
                  "probe_seed": 3407, "probe_algorithm": "random.Random(3407).sample(v2_index_rows, 146); sample order preserved",
                  "model_weights_loaded": False, "dummy_model_created": False, "swift_checks": checks,
                  "input_sha256": before, "new_data_sha256": {path.relative_to(ROOT).as_posix(): sha(path) for path in (DEV_PAIRS, DEV_INDEX, PROBE)}}
    write_json(ROOT / "reports/d3_dev_pairs_validation.json", validation)
    category_table = table(["rejected 종류", "개발 쌍", "학습 표본"],
                           [(name, validation["development_rejected_categories"].get(key, 0), validation["training_probe_rejected_categories"].get(key, 0))
                            for name, key in (("잘림", "truncated"), ("정상 종료 오답", "wrong"), ("추출 실패", "extract_fail"), ("긴 정답", "long_correct"))])
    check_table = table(["파일", "D1/v2 pair", "row", "종류", "프롬프트", "이미지 토큰", "chosen", "rejected"],
                       [(r["dataset"], r["pair"], r["row"], r["category"], r["prompt"], r["image_tokens"],
                         r["branches"]["chosen"]["completion"], r["branches"]["rejected"]["completion"]) for r in checks])
    paths = [DEV_PAIRS, DEV_INDEX, PROBE]
    paths += [ROOT / "scripts" / name for name in ("d3_prepare_dev_pairs.py", "d3_pair_preference.py", "d3_check_dev_pairs.py")]
    paths += [ROOT / "reports" / name for name in names[:2]]
    files = table(["새 파일", "SHA-256"], [(f"`{p.relative_to(ROOT).as_posix()}`", f"`{sha(p)}`") for p in paths])
    text = f"""# D3 개발 쌍 선호도 CPU 준비 보고

`HANDOFF_D3_cpu.md` 추가 작업 (2026-11-11), `PLAN_D3.md` 5절 보조 지표를 준비했다. **개발 146쌍**, 비교용 **학습 표본 146쌍**을 새 파일로 고정했다. 모델 가중치·dummy 모델은 만들지 않았고 GPU·API·설치·업로드 없이 끝냈다. 기존 파일·학습 설정·선택 규칙은 바꾸지 않았다.

## 고정 쌍과 표본

개발 쌍은 D1 707쌍 중 고정 개발 문항에 속한 146쌍이며 **{validation['development_questions']}개 문항**이다. Swift·index JSONL의 각 행과 개행까지 D1 원본 바이트 그대로 복사했고, 원래 D1 순서와 `pair` 번호를 유지했다. `pair`는 연속 재번호가 아닌 원본 식별자다. 학습 v2 611쌍과 문항 겹침은 **0건**이다.

학습 표본은 `random.Random(3407).sample(v2_index_rows, 146)`을 한 번 적용했다. 추출된 순서로 원본 index 행을 그대로 저장했고 중복 pair는 없다. 표본 종류는 `{dict(validation['training_probe_by_kind'])}`다. 실제 점수 계산에는 전체 v2 쌍 파일과 `--probe-index`를 함께 전달해 이 목록만 선택한다.

{category_table}

`fallback_wrong`은 정상 종료 오답에 합쳤다. 개발 최장: **{longest['longest']:,}토큰**, D1 pair `{longest['pair']}`, row `{longest['row']}`. 프롬프트 {longest['prompt']:,} + 더 긴 응답 {max(longest['chosen'], longest['rejected']):,}이며 이미지 토큰을 포함했다. 전 개발 쌍의 길이를 독립 계산했고 10,240 초과는 0건이다.

## 점수 스크립트

`scripts/d3_pair_preference.py`는 쌍 파일·index·M0 경로·후보 adapter 경로를 받는다. M0와 adapter 활성 후보의 chosen/rejected 응답 토큰 로그 확률 **합** 네 개를 기록한다. 같은 M0에 adapter를 얹고 기준 계산 때는 `disable_adapter()`를 사용한다. 둘 다 eval 모드이며 응답 생성은 하지 않는다.

Δ = (candidate chosen logp − M0 chosen logp) − (candidate rejected logp − M0 rejected logp).

길이 정규화나 β 곱을 적용하지 않는다. 선호 정확도는 **Δ > 0** 비율이며 Δ=0은 성공에 넣지 않는다. 전체와 rejected 종류별 선호 정확도·Δ 평균·중앙값을 낸다. 결과는 해석용으로만 쓰며 후보 선택에 넣지 않는다. 출력 폴더에는 응답 원문 없이 pair 식별자·네 logp·Δ·토큰 수를 가진 `pair_logps.jsonl`과 `summary.json`을 쓴다. 기존 출력 폴더가 있으면 중단한다.

```text
# 아래 GPU 점수 계산 명령은 작성만 했으며 실행하지 않았다.
# 상대 이미지 경로를 찾을 수 있는 이미지 루트에서 실행한다.
python scripts/d3_pair_preference.py --run --pairs data/d3_dev_pairs_swift.jsonl --index data/d3_dev_pairs_index.jsonl --base-model M0_LOCAL_PATH --adapter CANDIDATE_ADAPTER --output NEW_DEV_OUTPUT
python scripts/d3_pair_preference.py --run --pairs data/d3_pairs_v2_swift.jsonl --index data/d3_pairs_v2_index.jsonl --probe-index data/d3_train_probe_index.jsonl --base-model M0_LOCAL_PATH --adapter CANDIDATE_ADAPTER --output NEW_TRAIN_OUTPUT
```

기준 모델 경로에는 고정 M0 revision `ebb281ec70b05090aa6165b016eac8ec08e71b17`의 로컬 snapshot을 전달한다. 설치·다운로드 단계는 없고 실행 경로도 offline으로 고정했다. 이미지 해상도·ms-swift 3.12.3 DPO 템플릿·max_length 10,240·기본 loss_scale을 학습과 같게 사용한다. 프롬프트 label은 -100이며 잘린 rejected에는 EOS를 붙이지 않는다. causal shift로 첫 응답 토큰부터 마지막 응답 label까지 합산하고 padding은 제외한다.

## CPU 검증

개발 쌍에서 최장·잘림·정상 종료 오답·추출 실패를 포함한 **{sum(r['dataset'] == 'development' for r in checks)}쌍**, 학습 표본의 간결 쌍 2개를 추가해 **총 {len(checks)}쌍**을 확인했다. 실제 점수 스크립트의 `make_template`·`encode_pair`를 직접 호출했고, ms-swift JSONL 로더를 사용했다. 가중치 없는 로컬 processor만 읽었다. 전체 토큰 ID와 프롬프트/응답 label 범위가 독립 계산 및 기존 R1 프롬프트 경로와 일치했다. 잘림 EOS 생략도 통과했다. CPU에서 모델이 필요한 multimodal collator나 forward는 호출하지 않았다.

{check_table}

가짜 logp 및 작은 가짜 logits로 **{len(tests['checks'])}개 검사 통과**: 네 logp에서 Δ 산출, 엄격한 양수/동점 처리, 전체 평균·중앙값, 종류별 요약, M0 자기 비교 Δ=0, causal shift·첫 응답 토큰, 프롬프트·padding 제외, NaN 거부. 합성 Δ `[2, -1, 0, 3]`의 선호 정확도는 **50%**, 평균·중앙값은 **1**로 계산됐다. 이는 모델 성능 실측이 아니다.

실제 M0·후보 forward와 GPU logp 측정은 이번 범위에 없어 실행하지 않았다. 따라서 GPU 모델 로딩·multimodal collator·forward의 실행 검증은 아직 남아 있다.

## 새 파일과 SHA-256

{files}

이 보고서까지의 해시는 `reports/d3_dev_pairs_sha256.json`에 기록했다. 기존 입력·v1/v2 산출물·지침·계획 총 **{len(before)}개 파일**의 SHA-256이 전후 일치했다. MMMU/MMMU-Pro 자료에는 접근하지 않았다. 추가 CPU 준비를 완료하고 여기서 멈춘다.
"""
    # Write a separate report to preserve the existing v2 report exactly.
    report = ROOT / "reports/D3_DEV_PAIRS_REPORT.md"
    with report.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    paths.append(report)
    assert protected_hashes() == before
    write_json(ROOT / "reports/d3_dev_pairs_sha256.json", {p.relative_to(ROOT).as_posix(): sha(p) for p in paths})
    print("D3 development preference CPU preparation PASS", len(refs), "pairs;", len(checks), "token checks", flush=True)


if __name__ == "__main__":
    main()
