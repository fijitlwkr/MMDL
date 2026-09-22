# 오프라인 검증 기록 — 2026-09-21

팀 저장소 기준 commit: `aa11a7488e397dfb06699a9d6be71d7128420d88`.
이 도구를 검증하면서 추가 API 호출은 하지 않았다.

## 실제 저장소 raw 준비

| 항목 | `runs/draft/raw.jsonl` | `runs/run_max_new_tokens2048/raw.jsonl` |
|---|---:|---:|
| 기록된 max_new_tokens | 8192 | 2048 |
| 전체 / MC / open | 900 / 847 / 53 | 900 / 847 / 53 |
| stop / length | 792 / 108 | 666 / 234 |
| 규칙 자동 처리 | 565 | 491 |
| Judge 대상 | 335 | 409 |
| MMMU 규칙 + 랜덤 폴백 제거 | 450/900 (50.00%) | 390/900 (43.33%) |

두 raw는 ID별 질문 문맥·정답·선택지·기록된 이미지 정보·prompt token 수가 같았다. 원본 파일은 검증 전후 SHA-256이 같았다. 표의 MMMU 점수에는 Judge와 length gate가 없다. **2048의 하이브리드 최종 점수는 API 미실행으로 미완료**이며 위 MMMU 점수와 구분해야 한다.

## 기존 8192 API 응답 재집계

기존 실행과 새 도구의 335개 요청 payload 및 request hash가 모두 같은지 확인한 뒤, 기존 응답을 수정 없이 읽어 결과를 재현했다. 이 응답 파일은 이 PR에 포함하지 않았다. 팀원이 새 API 실행을 하면 새 Judge 판정이 달라질 수 있다.

| Judge snapshot | 재현한 정답 수 | 저장 usage 기반 비용 추정 |
|---|---:|---:|
| gpt-4.1-mini-2025-04-14 | 609/900 | $0.487914 |
| gpt-3.5-turbo-0125 | 577/900 | $0.6130075 |
| gpt-4o-mini-2024-07-18 | 581/900 | $0.18296355 |

각 실행에서 `summarize`를 반복했을 때 `summary.json`, `final_results.jsonl`, `REPORT.md`의 바이트가 같았다. 완료된 8192와 미완료 2048 비교에서는 전체 정확도 차이가 `null`로 남는 것을 확인했다.

## 자동 테스트

`python -m unittest discover -s assignment/experiments/raw_evaluation/tests -v`: 8개 통과.

- 오프라인 준비, 동적 Judge 대상 계산, 결과 폴더 이동 후 재집계
- 완료 Z 캐시 및 남은 요청만 실행, 비용 계산, 키 비저장
- 응답 불명확한 실패의 재시도 차단, 미완료 유지
- Judge length 종료를 정답 문자와 무관하게 추출 실패 처리
- 원본 사본 변조 시 호출 전 차단, 동시 실행 잠금
- 미완료 비교, Judge 모델 변경·질문 변경 시 비교 거절
- 중복 ID, 토큰 개수·length cap·prompt token 불일치, open 선택지 오류 거절

모든 자동 테스트의 HTTP 호출은 모의 응답이며 실제 자격 증명을 쓰지 않는다.
