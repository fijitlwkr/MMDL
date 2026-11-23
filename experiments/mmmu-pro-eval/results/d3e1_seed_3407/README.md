# D3-e1 (B_best) MMMU-Pro standard (10 options), seed 3407

| 항목 | 값 |
|---|---|
| 모델 | D3-e1 RNE 병합본 (M0 `Qwen/Qwen3-VL-4B-Instruct` rev `ebb281ec` + `MMDL-team4/hypB-d3e1-dpo`), 병합 샤드 SHA-256 `55011989…` / `2e8b706c…` (`records/model_sha256.txt`) |
| 데이터 | `MMMU/MMMU_Pro` `standard (10 options)` test, rev `0d7426df4ccb3d8704a992fe6850abee7c262127`, 1,730문항 (`pro_metadata.json`) |
| 평가 코드 | GitHub `exp/mmmu-pro-eval` `a08008b` (`experiments/mmmu-pro-eval/`) |
| 생성 | vLLM 0.11.0, RTX 4090 × 1, temperature 0.7, top_p 0.8, top_k 20, presence_penalty 1.5, 최대 8192토큰, seed 3407/3407 |
| 프롬프트 | MMMU와 같은 구조 (Question / Options / "Please select the correct answer from the options above."). MMMU-Pro 공식 프롬프트 아님 |
| 채점 | `hybrid100_mc_qwen_ab_open_no_length_gate_v2`, `Final Answer` 문자 범위 A~L. Judge `gpt-4.1-mini-2025-04-14` |
| raw SHA-256 | `c67aeb5f8650f7141b84af931a44e5b495b1875520753ee719afeeb62f2b15a1` |

## 결과

| 구분 | 정답 / 문항 | 정확도 | 과목 단순 평균 | 추출 실패 | length 종료 (정답) |
|---|---:|---:|---:|---:|---:|
| 전체 | 915 / 1,730 | 52.89% | 53.03% | 61 | 212 (44) |
| MMMU validation과 겹치지 않음 (`test_*`) | 619 / 1,153 | 53.69% | 53.42% | 35 | 134 (30) |
| MMMU validation과 겹침 (`validation_*`) | 296 / 577 | 51.30% | 52.29% | 26 | 78 (14) |

- 자동 1,198 / Judge 532 (규칙 미추출 529, 충돌 3). Judge 실패·pending 0, 비용 $0.90.
- 같은 코드로 평가한 baseline 결과는 아직 없다.

## 생성 기록

- 1차 실행이 766문항 저장 뒤 7번째 묶음(767~916번)에서 GPU 유휴·CPU 100% 상태로 40분 넘게 진행되지 않아 종료했다. 같은 출력 폴더에서 같은 config·seed로 767번부터 이어받았다(`records/generation_resume1.log`). 원인은 특정하지 못했다.
- `env.json`의 첫 invocation은 강제 종료로 `finished_at`이 비어 있다. `physical_gpu_memory.csv`는 1차, `_resume1.csv`는 2차 실행 기록이다.
- 단위 테스트 63 통과 / 2 실패: MMMU test 평가 패키지 회귀 기록에 원래부터 실패로 적힌 환경 의존 테스트 2개와 같다(`records/unit_tests.log`).

## 파일

- HF `MMDL-team4/hypB-eval-raw` `d3e1_mmmu_pro_seed_3407/` (커밋 `1cfe5b2b`)에 원본 전체. 여기에는 요약만 둔다.
- `raw.jsonl`, `run_metadata.json`, `env.json`, `env_check.json`, `logs/`, `worker.log`, `physical_gpu_memory*.csv`
- `summary/`: `REPORT.md`, `summary.json`, `final_results.jsonl`, `manifest.json`, `mmmu_summary.json`, `preparation_budget.json`
- `records/`: 모델 해시, 부속 파일 해시, preflight, 단위 테스트, 데이터 로드, 이어받기 로그
- `pro_metadata.json`: 문항 수, 과목별 수, ID 해시, 선택지 수, validation 겹침 목록
