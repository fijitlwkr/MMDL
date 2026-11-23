# D3-e1 (B_best) MMMU test, seed 3407

| 항목 | 값 |
|---|---|
| 모델 | D3-e1 RNE 병합본 (M0 `Qwen/Qwen3-VL-4B-Instruct` rev `ebb281ec` + `MMDL-team4/hypB-d3e1-dpo`), 병합 샤드 SHA-256 `5501198916f4184c8f02036b71097efa881e69d57c3b4d5a941e3aefc2a6fb21` / `2e8b706c5670049157ccd5273439a599bd2721d7d34c19016f7a7e0549e89540` |
| 데이터 | `MMMU/MMMU` test, rev `98e6ac0cb9b7b2cd2c991b85a50762edc4aedc68`, 10,500문항 (객관식 9,873, 주관식 627) |
| 평가 코드 | GitHub `exp/mmmu-test-eval`. 파드 생성 코드 `88a5f142`, 생성·평가 코드·설정은 `d8695313`과 같다. 빈 선택지 처리 `b57180d`, Judge 재개 `2f41eeb` |
| 생성 | vLLM 0.11.0, RTX 4090 × 2 (과목 고정 분할, GPU0 5,321 / GPU1 5,179), temperature 0.7, top_p 0.8, top_k 20, presence_penalty 1.5, 최대 8192토큰, seed 3407/3407 |
| 채점 | `hybrid100_mc_qwen_ab_open_no_length_gate_v2`, Judge `gpt-4.1-mini-2025-04-14` |
| raw SHA-256 | 합친 raw `92befe08e2cf27a02b88c10db1013d9219cf6d24d5c9386a875534a210017bac`, GPU0 `6a01b639…`, GPU1 `fbb8ed7d…` |

## 결과

| 구분 | 값 |
|---|---|
| 전체 정답 비율 | **66.07%** (6,937 / 10,500) |
| 30과목 단순 평균 | 67.29% |
| 객관식 / 주관식 | 65.76% (6,492 / 9,873) / 70.97% (445 / 627) |
| 처리 경로 | 자동 4,741 / 6,599, Judge 미추출 2,180 / 3,880, 충돌 16 / 21 |
| 추출 실패 | 439 |
| length 종료 | 1,504 (14.3%) |
| 의료 5과목 합계 (문항 수 가중) | 67.18% (1,177 / 1,752), 단순 평균 63.94% |
| Music | 35.03% (117 / 334) |
| Judge | 3,901건, pending 0, 기록 기준 비용 $5.90 |

## 채점 기록

- `test_Pharmacy_93`, `test_Pharmacy_126`은 원본 데이터에서 선택지 D가 빈 문자열이다. 점수를 보기 전에 "채점할 때만 끝의 빈 선택지를 뺀다"로 정했다(raw·프롬프트 불변). `summary/manifest.json`의 `trailing_empty_mc_options_removed`에 기록.
- Judge는 231건 뒤 HTTP 타임아웃 1건으로 멈췄다(`summary/errors.jsonl`). 응답을 받지 못한 그 1건만 다시 보내도록 실행 코드를 고친 뒤(`2f41eeb`) 이어서 끝냈다. 완료된 응답을 다시 부른 건은 0건.

## 파일

- HF `MMDL-team4/hypB-eval-raw` `d3e1_test_seed_3407/` (커밋 `035502e3`)에 원본 전체. 여기에는 요약만 둔다.
- `full/raw.jsonl`: 과목·문항 번호 순서로 합친 raw. `full/merge_receipt.json`: 합치기 검증 결과
- `full/gpu0/`, `full/gpu1/`: GPU별 raw, `run_metadata.json`, `env.json`, `env_check.json`, `logs/`, `worker.log`, `physical_gpu_memory.csv`
- `summary/`: `REPORT.md`, `summary.json`, `final_results.jsonl`, `manifest.json`, `mmmu_summary.json`, `preparation_budget.json`, `responses.jsonl`, `errors.jsonl`
- `records/`: 모델 해시, 부속 파일 해시, GPU 목록, preflight
