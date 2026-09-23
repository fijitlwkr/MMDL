# 오프라인 검증 기록 — 2026-09-23

## 현재 v2: length 게이트 제거

추론의 종료 사유가 아니라 규칙 추출 성공 여부와 충돌 여부로 경로를 결정한다. MC의 Qwen+Final Answer 100자 보완, open의 Qwen A/B 방식, Judge 설정·프롬프트는 동일하다. Judge 자체의 비정상 종료를 추출 실패로 처리하는 규칙도 유지한다.

아래는 고정 GPT-4.1-mini 저장 응답을 이용한 재계산이다. 모든 사용 요청의 payload·request hash·raw text hash가 기존 기록과 일치하고 원본 900행도 같은지 확인한 뒤, 새 요청 목록에 필요한 응답만 재사용했다. 추가 API 호출·재추론은 0회이며 HTTP 호출은 검증 중 차단했다.

| 입력 | 자동: v1 → v2 | Judge: v1 → v2 | 하이브리드 정답: v1 → v2 | MMMU 규칙 단독 |
|---|---:|---:|---|---:|
| 저장소 `runs/draft/raw.jsonl` (8192) | 565 → 582 | 335 → 318 | 609 → **608/900 (67.56%)** | 450/900 |
| 저장소 `runs/run_max_new_tokens2048/raw.jsonl` | 491 → 523 | 409 → 377 | API 미실행: v2 377건 미완료 | 390/900 |
| 9/22 별도 수신 `raw (1).jsonl` (8192) | 537 → 555 | 363 → 345 | 594 → **600/900 (66.67%)** | 452/900 |

두 8192 입력은 서로 다른 추론 결과다. 별도 수신 raw와 개인 API 응답은 Git에 포함하지 않는다. 각 입력 SHA-256:

- 저장소 8192: `003d09dabceae4167c9158c3b028b5c89671060d72182f4514a51dd0ad617c69`
- 저장소 2048: `6371cffb954125393eed87a508ea42b35045ac96b6932a31c9565c05cfb7cc81`
- 별도 수신 8192: `ef23f0c49d9b1ae6c62b9625fbd52cce474a0c035c1a644cfa737e0967daa313`

v2 `prepare`를 실제 세 raw에 실행했고 `judge_length` 경로가 없는 것을 확인했다. 완료된 두 입력은 `summarize` 반복 시 결과 파일이 바이트 단위로 일치했다. 원본 raw와 과거 v1 실행은 보존했다. 2048은 API 미완료여서 최종 정확도를 계산하지 않는다.

`python -m unittest discover -s assignment/experiments/raw_evaluation/tests -v`: **9개 통과**. 추가 테스트는 MC/open 규칙 성공·실패 및 MC 규칙 충돌이 stop/length에서 같은 경로로 처리되는지 확인한다. 기존 테스트의 Judge 비정상 종료 실패·재시도 방지·입력 검증도 통과했다.

## 과거 v1 검증 — 2026-09-21

아래는 length 게이트가 있던 당시 기록이며 현재 v2 점수와 구분한다.

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
