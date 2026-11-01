# 가설 B 평가 3단계 채점 기록 — 2026-11-01

E1·E2 prepare → Judge 108건 → 각각 summarize를 완료했다. pending은 모두 0이다.
기록된 실사용 토큰 기준 비용 합계는 $0.0591708이다. 키는 파일·로그·명령줄에 넣지 않았다.
4단계 집계·판정은 수행하지 않는다.

## 고정 조건과 PLAN

- work/eval_B_20261101/PLAN.md를 이 폴더의 PLAN.md에 바이트 그대로 동기화했다.
- 사용자 정정에 따른 본 기준: k0=10, 1차 기준 net_gain≥14.
- 참고 기준: k0=14였다면 net_gain≥18. 이번 3단계에서 어느 기준도 판정하지 않는다.
- main code/scoring/evaluate.py의 hybrid100_mc_qwen_ab_open_no_length_gate_v2를 그대로 사용한다.
- Judge: gpt-4.1-mini-2025-04-14, temperature=0, top_p=1, seed=3407, max_tokens=8.
- 평가 코드·config·raw·M0 결과는 수정하지 않았다. 실행 시작 Git은 97af99d9442e653b4a66276924cdf8b2c399a465이다.
- 평가 코드 기준 main은 016b3cf558e3dd9e366b277f5f871b28092a1379이며, verify_code.py의 40개 파일 검증을 실행 전후 통과했다.

## 입력과 API 없는 준비

| 실행 | 재확인한 raw SHA-256 |
|---|---|
| E1 | a6e307b88a0c8ab6afd4a76d6706004736ec4b8319a94a014e54fe0faa43e317 |
| E2 | 0026e5e6437f8c0ece78ca7c627847eff120783cc737e44faead4d41b8d92d1a |

결과 폴더는 로컬 work/eval_B_20261101/scoring/E1/, E2/이다.
prepare는 원본을 그대로 input/raw.jsonl에 복사하고 900 ID·30×30 및 원문 해시를 검증했다.

| 경로 | M0 (기존 완료) | E1 (완료) | E2 (완료) |
|---|---:|---:|---:|
| 자동 | 555 | 831 | 861 |
| Judge: 규칙 미추출 | 341 | 48 | 39 |
| Judge: 충돌 | 4 | 21 | 0 |
| Judge 합계 | 345 | 69 | 39 |
| 최종 추출 실패 | 36 | 34 | 29 |
| API pending | 0 | 0 | 0 |

규칙 미추출은 Judge로 보내는 사유이며 최종 추출 실패와 다르다.
prepare 시에는 Judge 69/39건이 남아 overall accuracy를 null로 유지했다.
완료 후에는 각 900문항이 모두 채점됐다. M0는 기존 결과를 읽기만 했고 재채점하지 않았다.

## 최종 점수

| 항목 | E1 | E2 |
|---|---:|---:|
| 전체 | 527/900 (58.56%) | 493/900 (54.78%) |
| 객관식 | 499/847 (58.91%) | 476/847 (56.20%) |
| 주관식 | 28/53 (52.83%) | 17/53 (32.08%) |
| pending | 0 | 0 |
| Judge 응답 | 69/69 | 39/39 |
| Judge 종료 사유 | stop 68 / length 1 | stop 39 |

v2의 비정상 종료·Z·추출 실패는 기존 규정대로 오답 처리했다.
API 오류는 0건이며 HTTP 200 응답 108건을 저장했다. 모든 응답 모델은 지정된 snapshot과 일치한다.
문항별 결과는 로컬에만 보관하고, [E1 요약](scoring_20261101/E1_summary.json)과
[E2 요약](scoring_20261101/E2_summary.json)에는 요청된 집단 통계와 provenance만 담았다.

## 비용 예산

공식 [GPT-4.1 mini 요율](https://developers.openai.com/api/docs/models/gpt-4.1-mini)을 2026-11-01 확인했다.
config와 같이 100만 토큰당 입력 $0.40 / 캐시 입력 $0.10 / 출력 $1.60이다.

| 실행 | Judge 총 호출 수 | 보수적 비용 상한 |
|---|---:|---:|
| E1 | 69 | $0.1890740 |
| E2 | 39 | $0.0220876 |
| 합계 | 108 | $0.2111616 |

요청 JSON의 UTF-8 바이트 수 + 요청당 입력 128토큰 여유분으로 입력 토큰을 상한 추정했다.
캐시 할인은 적용하지 않고 출력은 매 호출 max_tokens=8을 모두 사용하는 것으로 계산했다.
정밀 tokenizer 계산이나 청구서 금액은 아니다. 합계가 사용자 예산 $3 이하이므로 실행한다.
E1의 소량 5건은 전체 69건에 포함되며 완료 응답은 재호출하지 않는다.

| 실사용 기록 | E1 | E2 | 합계 |
|---|---:|---:|---:|
| 입력 토큰 | 136,067 | 11,400 | 147,467 |
| 캐시 입력 토큰 | 0 | 0 | 0 |
| 출력 토큰 | 76 | 39 | 115 |
| usage 기준 비용 | $0.0545484 | $0.0046224 | $0.0591708 |

비용은 API usage와 config의 동일 요율로 계산한 recorded response cost이다.
계정 청구서·크레딧 적용액을 조회한 값은 아니다. 사용자 예산 $3 이하로 완료했다.

## 런처와 보관

- run_judge.ps1가 새 PowerShell 창에서 judge_runner.py를 실행한다.
- getpass로 키를 한 번 입력받아 Python 런처의 OPENAI_API_KEY에만 두고 자식 evaluator에 상속한다.
  키를 파일·로그·명령줄·사용자 환경 설정에 넣지 않고, 종료·실패 시 환경변수에서 제거한다.
- E1 run --limit 5 → 요청 snapshot·응답 건수·frozen evaluator의 스키마 검증 확인 → E1 run 전체 → E2 run 전체 → 각각 summarize 순서이다.
  pilot의 정오답으로 설정이나 진행 여부를 고르지 않는다. Z도 기존 정책대로 처리한다.
- 로그·상태는 로컬 scoring/judge_launcher/에 남긴다. API 오류는 pending으로 보존하고 자동 재시도하지 않는다.
  frozen evaluator가 unresolved attempt를 발견하면 기록 검토 전 재호출을 막는다. journal·캐시를 지우지 않는다.
- raw·문항별 채점·요청·응답·HTTP receipt는 로컬에만 보관한다. Git에는 요약·스크립트만 보관한다.

## 런처 운영 검사 수정 기록

최초 E1 5건은 API 오류 없이 저장됐으나, 런처가 finish_reason=length인 1건을 중단 조건으로 잘못 검사했다.
v2는 비정상 종료·Z·빈 답을 완료된 추출 실패·오답으로 처리한다. 런처의 stop 강제 조건을 제거해
이 기존 정책을 그대로 따른다. 평가 코드·config·5건의 응답과 판정은 수정하거나 재호출하지 않는다.
이미 5건이 있으면 소량 시험을 다시 호출하지 않고 snapshot·건수 확인 후 남은 요청만 실행한다.
첫 런처가 종료하며 키를 삭제했기 때문에 재개 창에서 키를 다시 한 번 입력받는다.

재개를 완료했고 두 모델 모두 pending=0이다. 최초 5건의 responses·HTTP receipt·journal 바이트 prefix가
그대로임을 [캐시 검증](scoring_20261101/pilot_cache_verification.json)으로 확인했다.
API 시도·응답은 E1 각 69건, E2 각 39건이며 중복 호출이나 API 오류는 없다.
런처 [최종 실행 요약](scoring_20261101/execution_summary.json)은 complete 상태이다.
본 기준 k0=10(≥14)과 참고 k0=14(≥18)는 기록만 했고, net_gain·안전 기준·가설 판정은 계산하지 않았다.
