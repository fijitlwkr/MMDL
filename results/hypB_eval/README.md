# 가설 B 후속 실험 — MMMU validation 결과

baseline과 같은 평가 절차다 (`code/`, MMMU validation 900문항, RTX 4090, vLLM 0.11.0, 채점 `hybrid100_mc_qwen_ab_open_no_length_gate_v2`, Judge `gpt-4.1-mini-2025-04-14`).
폴더 이름의 seed는 `sampling.seed`이고 `engine_seed`는 모두 3407이다.

| 모델 | seed | 정답 / 900 | 정확도 | length 종료 | 추출 실패 |
|---|---|---|---|---|---|
| M0 (baseline, `results/mmmu_team_baseline/`) | 3407 | 600 | 66.67% | 128 | 36 |
| E3 | 3407 | 597 | 66.33% | 153 | 28 |
| D1 | 3407 | 602 | 66.89% | 101 | 40 |
| D2' | 3407 | 594 | 66.00% | 106 | 34 |
| D3-e1 | 3407 | 603 | 67.00% | 102 | 32 |
| D3-e1 | 42 | 603 | 67.00% | 100 | 36 |
| AB1 | 3407 | 595 | 66.11% | 106 | 42 |

참고: M0를 seed 42 / 1234 / 2026으로 평가한 결과는 596 / 593 / 602 (`exp/baseline-seed-robustness` 브랜치).

## 파일

| 파일 | 내용 |
|---|---|
| `raw.jsonl.gz` | 생성 원문 |
| `run_metadata.json`, `env.json`, `env_check.json`, `generation_summary.json` | 생성 설정·환경·요약 |
| `item_results.jsonl.gz` | 문항별 최종 채점 결과 |
| `scoring_summary.json`, `mmmu_summary.json`, `scoring_manifest.json` | 채점 요약과 입력 해시 |
