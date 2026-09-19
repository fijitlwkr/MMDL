# 공통 Judge 실행

**현재 범위(v0.8): VLMEvalKit 추가 실험은 보류한다.** 실행기의 기본값은 기존 3파서를 보존하므로, 이후 실행에서는 아래처럼 정책을 명시한다. 기존 캐시를 재사용하기 위해 코드 기본값은 변경하지 않았다.

```bash
python judge_runner.py --run results/legacy9048 --out results/legacy9048_judge --policies qwen__always_judge mmmu_no_random__always_judge hybrid100__always_judge --budget-usd 0.10
```

위 명령은 **API 호출 없는 dry-run**이다. 이번 후속 검토에서 추가 유료 호출은 하지 않았다. [H1/H2 검토 결과](../../reports/mmmu_parser_focused_review_20260919.md).

후속 실제 로그 시험: [899문항 파서 비교 + 실제 Judge30건](../../reports/mmmu_parser_pilot_20260919.md). Pod v2에는 legacy 입력의 미기록 토큰 보존·오류 격리 기능을 추가했다. HF 최종 입력 검사는 완화하지 않았다. 아래 합성 1건 기록과 실제 참고 시험을 구분한다.

Qwen·MMMU(no random)·VLMEvalKit의 Judge 대상 합집합을 한 번 처리하고, 세 정책에서 같은 응답을 재사용한다. 기본은 세 파서의 `always_judge`: length는 자동 채택하지 않는다. 파서별로 API를 반복 호출하지 않는다.

## 고정값

- 모델 `gpt-4.1-mini-2025-04-14`, temperature=0, top_p=1, seed=3407, 출력 8토큰, 원문 전체.
- 원본 Qwen Judge 프롬프트 및 Judge 응답의 Qwen 규칙 추출 유지. MC 프롬프트에 GT 추가 안 함. open은 기존 A=참조답/B=Other Answers 방식을 사용.
- `Z`, 유효 선택지 추출 실패, Judge 응답 자체의 length 종료는 완료된 추출 실패. 의미적 재시도·랜덤 폴백 없음.
- API 오류/중단은 pending. 마지막 요청의 청구 여부가 불명확하면 자동 재호출하지 않는다.
- 기본 비용 제한 $1.00. UTF-8 바이트 기반 보수적 요청 비용과 기존 usage를 확인하고, 초과할 다음 요청 전에 멈춘다. 예산 안에 전량 완료를 보장하지 않는다.
- 별도 패키지 설치 없이 Python 표준 라이브러리와 이 폴더의 고정 파서 사용.

## 실제 HF 결과를 받았을 때

폴더 이름 `hf_run1`은 예시다. 실제 run마다 경로를 분리한다.

```bash
python lab.py prepare --predictions /workspace/mmdl/hf_baseline/results/predictions.jsonl --config /workspace/mmdl/hf_baseline/config.json --source-kind hf-final --out results/hf_run1
python judge_runner.py --run results/hf_run1 --out results/hf_run1_judge --policies qwen__always_judge mmmu_no_random__always_judge hybrid100__always_judge
python judge_runner.py --run results/hf_run1 --out results/hf_run1_judge --policies qwen__always_judge mmmu_no_random__always_judge hybrid100__always_judge --execute --budget-usd 1.00
python lab.py merge-judge --run results/hf_run1 --judge results/hf_run1_judge/judge_results.jsonl --model gpt-4.1-mini-2025-04-14 --out results/hf_run1_scores.json
```

`--execute`가 없으면 API 호출 0회인 dry-run이다. 실제 요청에는 `OPENAI_API_KEY` 환경변수가 필요하다. 키를 커맨드 인자·파일·채팅에 넣지 않는다. 키는 로그에 기록하지 않는다.

중단 후 동일 설정으로 다시 실행하면 완료된 응답을 재사용한다. `--limit 10`은 **이번 실행의 신규 호출 수** 제한이다. 비용 제한은 같은 캐시에 쌓인 누적 사용량 기준이다. 여러 번 실행해도 비용 예산이 새로 리셋되지 않는다.

추후 VLMEvalKit 실험을 다시 진행하기로 하면 같은 캐시에 정책을 추가할 수 있다:

```bash
python judge_runner.py --run results/hf_run1 --out results/hf_run1_judge --policies qwen__always_judge mmmu_no_random__always_judge vlmevalkit__always_judge hybrid100__always_judge
```

먼저 dry-run으로 추가 대상과 예산을 확인한다. 동일 명령에 `--execute`를 붙이면 새로 필요한 문항만 호출한다. `needed_by`뿐 아니라 고정된 문항별 라우팅을 검증하여 합집합을 결정한다.

## 출력

| 파일 | 용도 |
|---|---|
| judge_settings.json | 설정·코드 해시와 원본 run 연결 |
| judge_results.jsonl | 문항별 공통 응답, 파싱 결과, usage·지연·모델·fingerprint |
| api_attempts.jsonl | API 호출 전 비용 예약·문항·요청 해시 기록 |
| execution_summary.json | 완료/실패/pending, 합집합 지출 및 정책별 단독 비용 |
| invocations.jsonl | 실행별 선택 정책·한도·신규 호출 수 |
| runner.lock | 동시 실행 방지; 정상 종료 시 제거 |

`execution_summary.json`은 다음 진단도 포함한다:

- length MC/open 각각의 유효 답·Z·기타 추출 실패·API 오류·pending.
- 유효 답 그룹 GT 정답률과 전체 length 그룹 점수 하한. 두 분모를 구분한다.
- 같은 유효 MC 그룹의 평균 1/K 참고값. 25% 고정 가정이나 “추측한다”는 판정을 하지 않는다.
- 선택지 수 분포, A–D 밖 선택지가 있는 문항 및 그중 Judge 대상 수. 프롬프트 한계의 노출 규모이며 오채점 수가 아니다.
- 정책별 비용은 서로 겹친다. 이 비용들을 합하여 실제 지출로 보고하지 않는다.

API 실패는 계정/연결 문제를 확인한 뒤 해당 요청의 처리·청구 상태를 검토해야 한다. 실행기에서 무조건 재시도하거나 기존 로그를 지우고 재호출하지 않는다. 시작 로그만 있고 결과가 없는 경우도 같다. 프로세스 강제 종료 후 남은 lock은 실제 실행 중인지 확인한 뒤 처리한다.

## 소프트웨어 검증

```bash
python -m unittest discover -s . -p 'test*.py' -v
```

로컬 및 Pod에서 32개 테스트 통과(기존18+실행기14). 원본 준비→모의 API→재개→merge, 중복 과금 방지, 오류 비밀정보 비출력, 잘못된 모델/usage/캐시, 비용 중단, Z 무재시도, length와 A–D 진단을 검사했다. 실제 MMMU 성능이나 Judge 추출 충실도를 측정한 것이 아니다.

`examples/connection_input/`은 합성 1문장이다. `finish_reason=length`와 토큰 수는 테스트를 위해 작성한 값이며 실제 추론 로그가 아니다. 연결 검사 결과는 `synthetic-demo`로만 처리한다.

### Pod 통합 확인 — 2026-09-19

- 배치 경로: `/workspace/mmdl/scoring_lab_20260919_v1`.
- `prepare → dry-run → execute → resume → merge-judge` 성공.
- Qwen/MMMU/VLMEvalKit 세 정책의 대상 1건을 합쳐 API **1회** 호출. 응답 B/stop, 입력242/출력1, 1.619초, usage×비캐시 단가 **$0.0000984**. 검사 예산은 $0.01이었다.
- 같은 캐시로 재실행했을 때 **신규 호출 0회**, 누적 1회, pending 0. 세 정책이 같은 캐시를 사용함을 확인했다. 정책별 비용을 합산하여 3회 비용으로 세지 않는다.
- 결과: `checks/shared_connection_judge/`, `checks/shared_connection_scores.json`, `checks/integration_acceptance.json`.
- 앞선 HF hybrid runner 연결 검사 1회($0.0000928)와는 별개다. 두 연결 검사 합계는 API 2회, usage 환산 $0.0001912다.
- 실제 HF 900문항 평가와 사람 라벨링은 미실행. 연결 결과의 정답률을 MMMU 점수로 보고하지 않는다.
