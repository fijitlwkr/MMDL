# DECISIONS

    - baseline: 미정 (확정되면 `runs/A` 또는 `runs/B`)
    - 상태: draft  (candidate → approved)
    - 새 공지 원문: (링크 또는 요약)

## 1. 고정된 결정

값은 `src/config.yaml`에만 씁니다. 여기에는 결정과 근거만 적습니다.

| 항목 | 결정 | 근거 | 소유 |
| --- | --- | --- | --- |
| 추론 setup | 공유 고정 setup (`src/config.yaml` 참조) | 팀 회의 | 추론 |
| 프롬프트 | Qwen3-VL 공식 MMMU 템플릿 (`Qwen3-VL/evaluation/mmmu/run_mmmu.py`) | 공식 evaluation 구조 사용 | 추론 |
| 파싱 실패 | 오답 처리 | | 실험 |
| 주관식 문항 | MMMU 원본 `parse_open_response` + `eval_open` | | 실험 |
| length 초과 응답 | judge로 처리 (파서 결과와 무관) | | 실험 |
| 추론 결과 raw | 후처리 없이 원문 저장, 수정 금지 | | 추론 |
| judge 결과 | `judge_raw.jsonl`로 저장 (API 키 없이 재현) | | 실험 |
| baseline 선정 | 정확도가 아니라 완전성(900/900, 에러 0) | | 추론 |

## 2. 실험 채택 규칙과 결과

규칙은 **결과를 보기 전에 커밋**합니다.

| # | 채택 규칙 | 결과 |
| --- | --- | --- |
| 1. 객관식 파서 (Qwen 공식 vs MMMU 공식) | 사람 라벨 일치율이 높은 쪽. 차이가 작으면 MMMU 공식 | |
| 2. judge (gpt-4.1-mini / gpt-4o-mini / gpt-3.5-turbo) | 라벨 일치율이 높고 선택지 날조 오채점이 적은 쪽. 차이가 작으면 gpt-4.1-mini | |

## 3. 재추론 트리거

- 재추론 필요: 프롬프트, sampling, 이미지 처리, max tokens, 컨텍스트 초과 처리 규칙 변경 / 육안 라벨링에서 프롬프트·전처리 버그 발견
- 재추론 불필요: 파서, judge, 채점 규칙 변경 (raw를 다시 읽으면 됨)

## 4. Open issues

- [ ] 컨텍스트 초과(입력 토큰 > 상한) 문항 처리 규칙 (9/20 밤)
- [ ] raw 용량 처리: git 그대로 / gzip / LFS (9/20 밤)
