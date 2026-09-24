"""Prepare fixed model-failure and gate-change reviews; no inference or API scoring."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import random
import re
import sys
import zipfile

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT.parent / "submission"
sys.path.insert(0, str(ROOT.parent / "repetition"))
from analyze import read_rows, require, sha

SEED = 3407
DATASET_REVISION = "98e6ac0cb9b7b2cd2c991b85a50762edc4aedc68"
RAW_SHA = "ef23f0c49d9b1ae6c62b9625fbd52cce474a0c035c1a644cfa737e0967daa313"
ANSWER_STATES = ["explicit", "inferable", "ambiguous", "no_answer"]
ERROR_TYPES = ["visual_reading", "knowledge", "calculation_reasoning", "repetition_incomplete", "evaluation_issue", "uncertain"]


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_rows(path, rows):
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")


def select_failures(rows):
    rng, selected, strata = random.Random(SEED), [], []
    for subject in sorted({r["subject"] for r in rows}):
        pool = sorted((r for r in rows if r["subject"] == subject and not r["correct"]), key=lambda r: r["id"])
        require(len(pool) >= 2, "Need two policy errors per subject: " + subject)
        draw = rng.sample(pool, 2)
        selected.extend(r["id"] for r in draw)
        strata.append({"subject": subject, "policy_error_population": len(pool), "sample_size": 2,
                       "inclusion_probability": 2 / len(pool), "population_weight_per_item": len(pool) / 2})
    return sorted(selected), strata


def fenced(text):
    fence = "`" * max(3, 1 + max((len(m.group()) for m in re.finditer(r"`+", text)), default=0))
    return fence + "text\n" + text + "\n" + fence


def instructions(kind):
    shared = """원문 전체와 이미지를 확인하고, labels.jsonl을 복사해 reviewer·검토 필드를 작성한다. 제공된 빈 원본은 보존한다. 자동 생성 라벨과 이전 챗의 답을 사람 라벨로 복사하지 않는다.

answer_status는 explicit(명시된 답), inferable(문맥에서 하나로 확정 가능한 답), ambiguous(복수 결론이 남음), no_answer(응답에서 답을 판단할 근거가 없음) 중 하나다. Final Answer 표기가 없어도 판단할 수 있으면 inferable로 기록한다. length 종료만으로 no_answer로 만들지 않는다. 문제를 새로 풀어서 모델이 말하지 않은 답을 보충하지 않는다. 명시적인 최종 수정이 있으면 이전 가정보다 우선한다.

human_answer는 객관식의 실제 선택지 문자, 주관식의 답 원문이다. 주관식에 평가용 A/B를 쓰지 않는다. ambiguous/no_answer일 때는 비워 둔다. evidence_quote는 모델 응답의 정확한 인용, inference_note는 문맥 추론이 필요한 경우의 근거다. reviewer와 review_status=done을 작성하기 전까지 완료 라벨로 세지 않는다.

이미지는 고정 MMMU revision에서 raw.image_indices 순서로 추출한 원본 파일이다. 각 batch 문서에 이미지와 raw_text 전문이 있다. 문서가 길어 뷰어가 생략하면 다운로드해서 전문을 읽는다. 사람이 실제로 확인한 경우에만 images_checked=true로 바꾼다.
"""
    if kind == "gate18":
        return """# 게이트 변경 18건 — 블라인드 답 판단

객관식 15건·주관식 3건이다. 주관식 53건 전체 검토는 이번 범위에서 제외했다. 6건씩 3개 batch로 나눴다.

이 ZIP에는 gold·기존 파서·Judge 답·정오를 넣지 않았다. 검토자는 이 ZIP만 받고, 저장소의 원본 raw·채점 결과·coordinator 대조표는 라벨 확정 뒤 확인한다. 이미 같은 문항의 정답/판정을 본 경우 prior_exposure=true와 notes에 남긴다. 이 방식은 배포 절차상의 블라인드이며 저장소 파일의 접근 통제는 아니다.

""" + shared + """
검토자가 각자 사본에서 답 판단을 완료한 뒤 라벨을 고정한다. 그 다음 취합 담당자가 coordinator/gate18_answer_key.jsonl로 gate-on Judge와 gate-off 자동 규칙을 비교한다. 의견이 다르면 근거 원문으로 조정하며, 공식 gold와 같다는 이유로 사람 추출 라벨을 고치지 않는다. 이 18건의 일치율은 전체 900건 추출 정확도의 추정값이 아니다.
"""
    return """# 모델 실패 유형 60건 — 원문 근거 검토

현재 정책상 오답 300건 중 과목별 2건씩 추출했다(30과목, 표본추출 seed 3407). 추론 seed와 별개다. 10건씩 6개 batch이며, reference_gold를 보여주는 원인 분석용 자료다. 골드를 숨기는 답 추출 실험과 구분한다.

""" + shared + """
primary_type은 아래 한 가지를 선택하고, 함께 나타난 현상은 secondary_types에 기록한다. 근거 없이 이미지·지식 오류를 단정하지 말고 uncertain을 허용한다.

| 값 | 판정 근거 |
|---|---|
| visual_reading | 실제 이미지의 문자·기호·도형 관계를 응답이 다르게 읽은 위치를 특정 |
| knowledge | 필요한 개념·사실을 잘못 적용한 명시적 서술을 특정 |
| calculation_reasoning | 입력을 읽은 뒤의 계산·논리 단계에서 잘못된 전개를 특정 |
| repetition_incomplete | 반복·자기수정이 이어지며 답 확정에 실패한 원문 근거. 단순히 길거나 length인 것만으로 분류하지 않음 |
| evaluation_issue | 모델 응답의 답과 저장 채점의 오답 판정이 어긋난다는 근거. 취합자가 기존 판정과 추가 대조 |
| uncertain | 자료만으로 원인을 구분할 수 없음. 부족한 근거를 notes에 기록 |

원인 판정은 evidence_quote와 image_evidence/diagnosis에 근거를 남긴다. 개선 아이디어는 improvement_target에 짧게 기록한다. 실제 답이 올바르게 표현됐다고 보이면 model_answer_correct=true로 기록하되, 기존 점수는 이 검토만으로 덮어쓰지 않는다. 수치 동치가 허용오차에 달렸다면 tolerance_dependent=true와 이유를 남긴다.

과목당 오답 수가 달라 60건의 단순 비율을 300건 전체 비율로 쓰지 않는다. 취합 시 과목별 오답 수/2의 가중치를 쓰고, 표본 수·선정법·미확정 수를 함께 표시한다. 이는 정책상 오답 집단의 분석이며 정책상 정답 안의 채점 오류를 추정하지 않는다. 각 과목 2건이라 과목별 실패율을 정밀하게 추정할 표본은 아니다.
"""


def make_packet(out, kind, ids, raw, images):
    folder = out / kind
    folder.mkdir()
    (folder / "README.md").write_text(instructions(kind), encoding="utf-8")
    batch_size = 10 if kind == "failure60" else 6
    labels, batches = [], []
    for start in range(0, len(ids), batch_size):
        batch = ids[start:start + batch_size]
        batch_name = f"batch_{start // batch_size + 1:02d}.md"
        lines = [f"# {kind} / {batch_name}", "", "검토 기준은 README.md, 기록 양식은 labels.jsonl을 사용한다.", ""]
        for id_ in batch:
            row = raw[id_]
            lines += [f"## {id_}", "", f"유형: {row['question_type']} / 종료 기록: {row['finish_reason']}", "",
                      "### 실제 프롬프트", "", fenced(row["prompt"]), "", "### 모델에 입력된 이미지", ""]
            for item in images[id_]:
                # packets/<cohort>/batch.md -> experiment/images (also preserved in ZIP).
                lines += [f"image {item['image_index']}:", "", f"![{id_} image {item['image_index']}](../../{item['path']})", ""]
            if kind == "failure60":
                lines += ["### 참조 정답 (원형)", "", fenced(str(row["gold"])), ""]
            lines += ["### 응답 전문", "", fenced(row["raw_text"]), ""]
            label = {"id": id_, "batch": batch_name, "source_sha256": RAW_SHA,
                     "raw_text_sha256": hashlib.sha256(row["raw_text"].encode()).hexdigest(),
                     "question_type": row["question_type"], "reviewer": "", "review_status": "pending",
                     "prior_exposure": None, "images_checked": False, "answer_status": "", "human_answer": "",
                     "evidence_quote": "", "inference_note": "", "notes": ""}
            if kind == "failure60":
                label.update(primary_type="", secondary_types=[], image_evidence="", diagnosis="",
                             improvement_target="", model_answer_correct=None, tolerance_dependent=None)
            labels.append(label)
        (folder / batch_name).write_text("\n".join(lines) + "\n", encoding="utf-8")
        batches.append({"file": batch_name, "ids": batch, "count": len(batch)})
    write_rows(folder / "labels.jsonl", labels)
    require(all(r["review_status"] == "pending" and not r["human_answer"] and not r["evidence_quote"] for r in labels), "Labels must remain blank")
    return batches


def make_zip(out, kind, ids, image_manifest):
    selected_images = [image for image in image_manifest["images"] if image["id"] in ids]
    # A reviewer ZIP never contains the coordinator directory or the other cohort.
    with zipfile.ZipFile(out / f"{kind}_review.zip", "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted((out / kind).iterdir()):
            archive.write(path, f"packets/{kind}/{path.name}")
        archive.writestr("README.md", f"# 검토 시작\n\n[검토 안내](packets/{kind}/README.md)를 먼저 읽는다. "
                          f"배치 문서와 빈 labels.jsonl은 `packets/{kind}/` 안에 있다. 이미지 폴더의 위치를 바꾸지 않는다.\n")
        for item in selected_images:
            archive.write(ROOT / item["path"], item["path"])
        archive.writestr("image_manifest.json", json.dumps({"dataset_repo": "MMMU/MMMU", "dataset_revision": DATASET_REVISION,
                                                            "split": "validation", "images": selected_images}, ensure_ascii=False, indent=2) + "\n")


def prepare(out):
    require(not out.exists() or not any(out.iterdir()), "Use a new empty output directory; never overwrite human labels")
    require(out.resolve().parent == ROOT, "Output must be a direct child of this experiment directory for portable image links")
    require(not SOURCE.resolve().is_relative_to(out.resolve()), "Output must not contain source")
    raw_path, result_path = SOURCE / "input/raw.jsonl", SOURCE / "results/item_results.jsonl"
    hashes = {"raw": sha(raw_path), "item_results": sha(result_path), "changed_items": sha(SOURCE / "results/changed_items.jsonl"),
              "image_manifest": sha(ROOT / "image_manifest.json")}
    require(hashes["raw"] == RAW_SHA, "Wrong raw snapshot")
    scores = json.loads((SOURCE / "results/scores.json").read_text(encoding="utf-8"))
    require(scores["source_sha256"] == RAW_SHA and scores["final"]["overall"]["correct"] == 600, "Wrong score snapshot")
    raw = {r["id"]: r for r in read_rows(raw_path)}
    results = read_rows(result_path)
    require(set(raw) == {r["id"] for r in results} and len(raw) == 900, "ID coverage mismatch")
    require(sum(not r["correct"] for r in results) == 300, "Expected 300 policy errors")
    for r in results:
        require(all(r[k] == raw[r["id"]][k] for k in ("gold", "subject", "question_type", "finish_reason", "output_tokens")), "Row mismatch: " + r["id"])
    selected, strata = select_failures(results)
    changed = read_rows(SOURCE / "results/changed_items.jsonl")
    gate_ids = sorted(r["id"] for r in changed)
    require(len(selected) == 60 and len(gate_ids) == 18, "Cohort size mismatch")
    require(Counter(raw[id_]["question_type"] for id_ in gate_ids) == {"multiple-choice": 15, "open": 3}, "Gate cohort type mismatch")
    require(all(raw[id_]["finish_reason"] == "length" for id_ in gate_ids), "Expected length cohort")
    selected_set = set(selected) | set(gate_ids)
    image_manifest = json.loads((ROOT / "image_manifest.json").read_text(encoding="utf-8"))
    require(image_manifest["dataset_revision"] == DATASET_REVISION, "Wrong image revision")
    images = {id_: [] for id_ in selected_set}
    for item in image_manifest["images"]:
        require(item["id"] in selected_set, "Unexpected image ID")
        image_path = (ROOT / item["path"]).resolve()
        require(image_path.is_relative_to((ROOT / "images").resolve()) and sha(image_path) == item["sha256"], "Image path/hash mismatch")
        require(not any(k in item for k in ("gold", "answer", "predicted", "correct", "question")), "Answer data in image metadata")
        images[item["id"]].append(item)
    for id_, assets in images.items():
        by_index = {x["image_index"]: x for x in assets}
        require(len(by_index) == len(assets) and set(by_index) == set(raw[id_]["image_indices"]), "Image slot mismatch: " + id_)
        images[id_] = [by_index[i] for i in raw[id_]["image_indices"]]
    out.mkdir(parents=True, exist_ok=True)
    (out / "coordinator").mkdir()
    batches = {"failure60": make_packet(out, "failure60", selected, raw, images),
               "gate18": make_packet(out, "gate18", gate_ids, raw, images)}
    strata_by_subject = {s["subject"]: s for s in strata}
    selected_results = [r for r in results if r["id"] in selected]
    write_rows(out / "coordinator/failure60_selection_key.jsonl", [{**r, **strata_by_subject[r["subject"]]} for r in selected_results])
    write_rows(out / "coordinator/gate18_answer_key.jsonl", [{**r, "gold": raw[r["id"]]["gold"]} for r in changed])
    manifest = {"source_sha256": RAW_SHA, "input_sha256": hashes, "dataset_revision": DATASET_REVISION,
                "script_sha256_lf": hashlib.sha256(Path(__file__).read_text(encoding="utf-8").encode()).hexdigest(),
                "sampling": {"seed": SEED, "method": "random.Random(seed); sorted subjects; sorted policy-error IDs; sample 2 per subject",
                             "target_population": "300 policy-scored errors, not all 900 responses", "strata": strata},
                "failure60_ids": selected, "gate18_ids": gate_ids, "overlap_ids": sorted(set(selected) & set(gate_ids)),
                "failure60_types": dict(Counter(raw[x]["question_type"] for x in selected)),
                "failure60_finish": dict(Counter(raw[x]["finish_reason"] for x in selected)),
                "batches": batches, "human_reviews_completed": 0, "new_api_calls": 0, "new_inference_runs": 0,
                "answer_status_values": ANSWER_STATES, "primary_error_type_values": ERROR_TYPES}
    write_json(out / "coordinator/manifest.json", manifest)
    for kind, ids in (("failure60", selected), ("gate18", gate_ids)):
        make_zip(out, kind, ids, image_manifest)
        with zipfile.ZipFile(out / f"{kind}_review.zip") as archive:
            require(archive.testzip() is None, "Corrupt ZIP")
            require(not any("coordinator" in name or "answer_key" in name for name in archive.namelist()), "Coordinator leak")
        require(len(read_rows(out / kind / "labels.jsonl")) == len(ids), "Label count mismatch")
    require(sha(raw_path) == hashes["raw"] and sha(result_path) == hashes["item_results"], "Inputs changed")
    print(json.dumps({"failure60": len(selected), "gate18": len(gate_ids), "unique": len(selected_set),
                      "images": len(image_manifest["images"]), "human_reviews_completed": 0}, ensure_ascii=False))


def self_test():
    rows = [{"id": f"{s}_{i}", "subject": s, "correct": i == 9} for s in ("A", "B") for i in range(10)]
    a, strata = select_failures(rows)
    require(a == select_failures(list(reversed(rows)))[0], "Selection depends on file ordering")
    require(len(a) == 4 and not any(x.endswith('_9') for x in a), "Incorrect sample")
    require(all(x['population_weight_per_item'] == 4.5 for x in strata), "Incorrect weights")
    require(fenced('```\ntext').startswith('````text\n'), "Unsafe raw fence")
    print("Self-test passed: deterministic stratified selection, score filtering, weights, raw fencing.")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out", type=Path)
    p.add_argument("--self-test", action="store_true")
    args = p.parse_args()
    if args.self_test:
        self_test()
    else:
        require(args.out is not None, "Specify a new output directory")
        prepare(args.out.resolve())
