# Hypothesis B 평가 준비 — yoonseok

1단계 CPU 준비와 2단계 GPU 생성을 완료했다. E1·E2 각각 900문항 검증과 로컬 전송·해시 대조를 통과했다.
생성은 이미지 기본 Python(Torch 2.8.0+cu128), 기존 venv는 병합 전용으로 사용했다. Judge는 호출하지 않았다.
결과와 설치 변경 기록은 [GENERATION_REPORT_20261101.md](GENERATION_REPORT_20261101.md),
1단계 결과와 자원 추정은 [PREPARATION_REPORT.md](PREPARATION_REPORT.md), 고정 조건은 [PLAN.md](PLAN.md)에 있다.
raw·문항별 채점 결과는 외부 로컬 경로에 두고, 이 폴더에는 스크립트·ID 목록·요약만 보관한다.

## 파일

| 파일 | 역할 |
|---|---|
| prepare.py | M0·기존 seed/재실행 v2 결과 재현, 네트워크 차단 상태에서 점검 |
| aggregate.py | 두 raw와 두 v2 결과 폴더를 받아 128문항 v2 net_gain, 참고 MMMU 점수, 900문항 안전·기제·세부 통계 출력 |
| m0_length_ids.txt | SHA가 고정된 M0의 length 128문항 ID |
| preparation_v2/ | 재현 요약, 자기 비교, seed_42 비교, 기존 M0 생성 자원 요약 |
| verify_code.py / code_freeze.json | main code/ 전체 및 재사용 병합·분석 코드의 LF 정규화 SHA-256 확인 |
| setup_gpu.sh | 이미지 기본 Python에 main과 같은 requirements 설치, 설치 전후 cu128 Torch 메타데이터 확인. PEFT 추가 설치 없음 |
| prepare_model.py | 고정 revision 다운로드, 기존 학습 merge.py로 bf16 병합, processor 파일 동일성 확인 |
| run_gpu.sh | E1 → E2 병합·환경 게이트·900문항 preflight·생성·raw 검증 |
| run_metrics.py | 생성 metadata/raw 해시 대조, 생성 시간·토큰·VRAM 요약 |
| test_aggregate.py | net_gain 방향, pending 처리, 마커 단어 경계 회귀 점검 |

## CPU 재현

아래 명령은 MMDL 루트 기준이다. Python 표준 라이브러리만 사용한다.
출력은 기존 폴더를 덮어쓰지 않도록 새 경로를 지정한다.

~~~powershell
python -X utf8 work/hypB-train-git/assignment/experiments/hypB_eval/yoonseok/prepare.py --m0-raw assignment/experiments/received_20260922/results/input/raw.jsonl --m0-scores work/team-evaluator-no-length/assignment/experiments/raw_evaluation/outputs/release-v2-latest --seed-root work/error-analysis-A/results/baseline_seed_robustness --out work/eval_B_20261101/recheck_NEW
python -X utf8 -m unittest discover -s work/hypB-train-git/assignment/experiments/hypB_eval/yoonseok -p test_aggregate.py -v
~~~

## 두 실행 비교

각 --*-scores는 v2 manifest.json + final_results.jsonl 폴더이다.
기존 seed 실행의 scoring_manifest.json + item_results.jsonl 형식도 지원한다.
raw.jsonl.gz는 압축을 푼 원문 바이트로 SHA를 검증한다.

~~~bash
python aggregate.py \
  --left-raw /local/M0/raw.jsonl --left-scores /local/M0/v2 \
  --right-raw /local/E1/raw.jsonl --right-scores /local/E1/v2 \
  --length-ids m0_length_ids.txt --k0 "$AGREED_K0" \
  --out /local/NEW_COMPARISON.json
~~~

M0 vs E2, E1 vs E2도 같은 인터페이스이며, 128문항은 항상 M0 목록으로 고정한다.
방향은 오른쪽 − 왼쪽이다. 주 지표는 v2 점수이며 MMMU 규칙 점수는 참고이다.
k0는 필수 인자이며 아직 확정하지 않았다. 준비 점검 파일의 k0=0은 테스트 입력이다.
E1 vs E2의 decision 필드는 같은 수식을 적용한 참고값이며, PLAN의 최종 E1/E2 판정은 각각 M0와 비교한다.
문항별 pending이 있으면 해당 net_gain·정확도 차이·판정은 null이다.
raw ID·문항 입력·채점 정책·Judge 설정·원문 해시 불일치 시 중단한다.

방향 전환 과다는 지정된 8개 마커의 단어 경계·대소문자 무시 합계가 21 이상인 응답이다.
반복 후보는 기존 repetition/analyze.py를 그대로 사용한다.
MMMU 참고 점수는 main code/scoring/evaluate.py의 random fallback 제거 진단 함수를 그대로 사용한다.

## 2단계 전용 — baseline의 이미지 기본 Python으로 재개

이미지 기본 Python은 Torch 메타데이터 2.8.0+cu128을 유지한다. 게이트·config·requirements는 그대로 둔다.
기존 /workspace/hypB-eval-env는 PEFT 병합에만 사용하고 PATH에 넣지 않는다.

사용자가 준비한 RTX 4090 / runpod/pytorch:1.0.2-cu1281-torch280-ubuntu2404에서만 실행한다.
체크아웃·환경·캐시·결과는 모두 /workspace 아래에 두고 HF_HOME=/workspace/hf_cache를 사용한다.
HF 로그인은 사용자가 먼저 수행하며 토큰을 인자로 넣거나 로그에 기록하지 않는다.

~~~bash
cd /workspace/MMDL/assignment/experiments/hypB_eval/yoonseok
bash setup_gpu.sh
bash run_gpu.sh /workspace/hypB_eval_NEW smoke
# smoke가 통과한 뒤 각각 새 E1/, E2/에서 시작한다.
bash run_gpu.sh /workspace/hypB_eval_NEW E1
bash run_gpu.sh /workspace/hypB_eval_NEW E2
~~~

고정 다운로드:

| 구성 | 저장소 | revision |
|---|---|---|
| 원본 | Qwen/Qwen3-VL-4B-Instruct | ebb281ec70b05090aa6165b016eac8ec08e71b17 |
| E1 adapter | MMDL-team4/hypB-e1-structured-3k | 0de38ff61af238608dc7be53358f1dac23788995 |
| E2 adapter | MMDL-team4/hypB-e2-answer-3k | 72e45c1bb07eb79179739fae949ccf80f21e891b |

평가 코드·config.yaml을 바꾸지 않고 병합 모델 경로만 main 생성 스크립트에 넘긴다.
main --install의 기본 설치 단계도 그대로 사용하며, Torch 버전이 달라지면 중단한다.
환경 설치, 게이트, preflight, 생성, raw 검증 중 실패하면 즉시 중단한다.
900 고유 ID·과목별 30행·오류 없음은 main 검증기를 재사용한다.
결과는 E1/E2별 merged/, model_receipt.json, gates/, preflight/, generation/, generation_summary.json과 로그이다.
생성 후 raw·해시를 로컬로 보관하고 보고한다. 자동 업로드·Judge 호출·파드 종료는 없다.
