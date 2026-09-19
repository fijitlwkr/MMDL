# 보존된 공통 Judge 실행기

이 파일은 기존 실험 실행기의 사용법입니다. 최신 팀의 최종 평가 파이프라인은 아직 승인되지 않았습니다. H1/H2 반환 라벨 재현은 README의 `reproduce_reviews.py`로 하며 API가 필요 없습니다.

## 정책과 설정

기존 Judge는 `gpt-4.1-mini-2025-04-14`, temperature 0, top_p 1, seed 3407, 출력 8토큰입니다. 실험 당시 값은 원래 코드와 기록에 보존합니다. 최종 채택 시 공통 설정 파일로 통합해야 합니다.

VLMEvalKit은 후보에서 제외했습니다. 과거 기본값을 바꾸어 기존 결과를 다른 코드로 재현했다고 주장하지 않도록 실행기 원본은 유지하며, 새 명령에는 사용할 정책을 반드시 명시합니다.

```bash
python judge_runner.py --run /path/to/prepared_run --out /path/to/new_judge_cache --policies qwen__always_judge mmmu_no_random__always_judge hybrid100__always_judge --budget-usd 1.00
```

위 명령은 dry-run입니다. `--execute`를 명시할 때만 실제 API 요청과 비용이 발생합니다. 키는 `OPENAI_API_KEY` 환경변수로 전달하고 저장하지 않습니다. 이 업로드 중에는 API를 호출하지 않았습니다.

같은 raw·프롬프트·모델·설정 해시의 요청만 캐시를 재사용합니다. 동일 Judge의 동일 문항 응답을 정책 사이에서 공유하며, 모델 비교를 수행하면 서로 다른 모델은 별도 캐시로 기록합니다. 현재 실행기는 단일 Judge용이며 3종 비교 구현이 완료된 것은 아닙니다.

## 출력과 한계

- `judge_results.jsonl`: 원본 응답, 추출 결과, 상태, usage·지연·fingerprint.
- `judge_settings.json`: 설정·코드·원본 run의 해시 연결.
- `api_attempts.jsonl`, `execution_summary.json`, `invocations.jsonl`: 요청·실패·pending·비용 기록.
- 완료된 Z/추출 실패는 오답입니다. API 오류·미완료는 pending이며 확정 점수로 보고하지 않습니다.
- open은 과거 A=참조답/B=Other Answers 방식도 포함합니다. 팀의 MMMU open 최종안과 같다고 취급하지 않습니다.

최종 팀 파일명 `judge_raw.jsonl`과 현재 실행기의 `judge_results.jsonl`은 이름과 스키마를 맞추는 작업이 필요합니다. 기존 응답을 덮어쓰거나 다른 모델의 응답으로 바꾸지 않습니다. 저장 캐시로 하는 재채점과 새 API 호출을 구분합니다.

API 30건 pilot의 수치는 [PILOT_899.md](legacy_pilot/PILOT_899.md), 당시 운영 기록은 [원문](legacy_pilot/SHARED_JUDGE_original.md)에 있습니다. 이 묶음에 전체 pilot API 캐시가 포함됐다고 주장하지 않습니다.
