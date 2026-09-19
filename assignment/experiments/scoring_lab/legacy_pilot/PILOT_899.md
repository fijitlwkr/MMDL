# 실제 저장 응답으로 수행한 파서·Judge 참고 테스트

## 범위

- 기존 TSV 기반 출력 cap 9048, 당시 sampling seed **42**의 저장 응답 900개를 검사했다. 현재 팀의 seed 3407 / HF 고정본 최종 실험이 아니다.
- `validation_Geography_15`는 GT=D인데 TSV annotation의 D가 NaN이며, 저장된 실제 생성 프롬프트에도 A–C만 있다. 입력 오류 1건을 `rejected.jsonl`에 격리하고 **899문항**을 비교했다. HF 내용으로 과거 응답의 선택지를 바꾸지 않았다.
- Pod의 고정 HF 입력(`/workspace/mmdl/hf_baseline/validation900.jsonl`)에서는 동일 문항의 D가 문자열 **`None`**, GT=D로 보존돼 있다. 기존 TSV에서 문자열 선택지가 결측값이 된 사례다. 이것이 다른 모든 입력 차이를 설명한다는 뜻은 아니다.
- 비교 집합: MC 846 / open 53, stop 784 / length 115. 과거 로그에 없는 입력 토큰 수는 null로 보존한다.
- `source_kind=legacy-pilot`: 부분집합 참고 실험임을 명시한다. 최종 HF 모드는 계속 전량 900개와 필수 메타데이터를 요구한다.
- GPU 재추론 없음. 실제 API 시험은 대상 ID순 첫 30건, 비용 상한 $0.10. 무작위 대표 표본이나 Judge 정확성 평가가 아니다.

## 1. 자동 처리와 Judge 대상

같은 899개 응답에 length 자동 채택 금지를 공통 적용했다. 자동 처리의 의미는 규칙이 유효한 답을 반환하여 API를 생략한다는 뜻이며, 사람이 충실한 추출이라고 확인했다는 뜻이 아니다.

| 파서 / 정책 | 자동 처리 | 비율 | 자동 처리 중 GT 정답 | Judge 대상 |
|---|---:|---:|---:|---:|
| Qwen 규칙 | 396 | 44.05% | 308 | 503 |
| MMMU 규칙, random fallback 제거 | 717 | 79.76% | 404 | 182 |
| VLMEvalKit 규칙 | 230 | 25.58% | 163 | 669 |
| 기존 hybrid100 보조 후보 | 572 | 63.63% | 418 | 327 |

**최종 정확도 표가 아니다.** 자동 처리 집합이 서로 다르고 Judge 미완료 문항이 남아 있다. MMMU의 자동 처리 수가 많다는 이유만으로 더 정확한 추출이라고 결론 내릴 수 없다. 위 수치는 THIRD_PARTY.md에 고정한 코드 버전에 한정한다.

주 비교 3종의 Judge 대상 합집합은 **801건**이다. 개별 대상 수 합계 1,354건을 정책마다 다시 호출하지 않는다. hybrid100은 이번 API 요청 범위에 별도로 추가하지 않았다.

## 2. H1: 정상 종료 객관식의 파서 일치

대상 stop MC는 **739문항**. 둘 다 추출에 실패한 경우는 답 일치 분모에서 제외했다.

| 비교 | 둘 다 추출 성공 | 같은 답 | 다른 답 | 공동 성공군 일치율 |
|---|---:|---:|---:|---:|
| Qwen–MMMU | 316 | 267 | **49** | **84.49%** |
| Qwen–VLMEvalKit | 146 | 144 | 2 | 98.63% |
| MMMU–VLMEvalKit | 180 | 138 | 42 | 76.67% |

Qwen–MMMU는 이 외에 Qwen만 성공 57, MMMU만 성공 356, 둘 다 실패 10개다. “거의 같은 답을 뽑는다”는 전제를 그대로 채택하기 어렵다. 사전 H1 기준은 팀에서 확정하지 않았으므로 공식 가설 검정의 확정 결론으로 쓰지 않는다.

Qwen–MMMU가 서로 다른 답을 뽑은 49개에 대해 질문·선택지·응답 원문이 포함된 블라인드 검토 파일을 만들었다. GT와 파서 출력은 숨겼다. 사람 라벨은 아직 없다. 이 49개만 검토해 전체 추출 충실도를 검증했다고 주장할 수 없다.

## 3. H3: 잘린 응답의 규칙 결과

length 중 MC는 107문항이다. 아래 표는 gate를 적용하기 전 규칙 진단이며, 이 답을 본 채점에서 자동 채택하지 않는다.

| 파서 | 유효 답 추출 | 그중 GT 정답 |
|---|---:|---:|
| Qwen | 9/107 | 4/9 |
| MMMU | 97/107 | 36/97 |
| VLMEvalKit | 21/107 | 14/21 |

open length 8개는 별도 처리: Qwen 유효2/정답2, MMMU 유효8/정답2, VLMEvalKit 유효0. open은 참조답 동치 채점과 관련되므로 MC 문자 추출과 합쳐 해석하지 않는다.

높은 추출률은 정답률이나 추출 충실도와 같지 않다. 서로 다른 성공 집합의 조건부 정답률로 파서 우열을 정하지 않는다. length 자동 채택 금지 방침을 바꿀 근거는 이 결과만으로 부족하다.

## 4. 실제 API 30건 시험

- 공통 Judge `gpt-4.1-mini-2025-04-14`, temperature=0, top_p=1, Judge seed=3407, 출력8토큰, 전체 응답 전달.
- 신규 호출 **30회**, 유효 답 **27건**, 추출 실패 **3건**, API 오류 **0건**. 실패 3건은 length MC에서의 Z 응답이다. Z 재시도와 랜덤 폴백 없음.
- usage×비캐시 단가 비용 **$0.0321316**. 청구서 실측은 아니며 캐시 할인·세금은 반영하지 않았다.
- API 보고 입력 **80,209토큰**, 출력 **30토큰**, 고유 문항30개. 누락 metadata 허용 범위를 legacy에 한정하는 검사 등을 포함해 로컬 및 Pod에서 소프트웨어 테스트 **36개** 통과.
- 801개 주 비교 대상 중 **771개 미완료**. 최종 파서별 hybrid 점수는 아직 산출하지 않았다. 이번 30건을 전체로 단순 환산한 정확도도 제시하지 않는다.
- 호출한 length MC 6건은 유효 답3/Z3이다. 유효 답 중 GT 정답1. 표본이 작고 ID순 선택이므로 Judge 추측 여부나 정확성을 판단하지 않는다.

## 다음 판단

1. 정상 종료 MC에서 Qwen–MMMU 불일치 49개를 사람이 확인한다.
2. 자동 처리 수와 실제 답 추출의 충실도를 분리해 H1/H2를 판단한다.
3. 최종 HF 900개 결과를 받은 뒤 동일 파서·공통 Judge 설정으로 본 비교를 수행한다. 이번 TSV pilot의 점수를 대체 결과로 쓰지 않는다.

## 파일과 재현

Pod 폴더: `/workspace/mmdl/scoring_lab_20260919_v2`.

- 원본: `/workspace/mmdl/results/mmmu_validation900_9048.jsonl` (수정하지 않음).
- `inputs/legacy9048/config.json`: 원본·summary·adapter 해시, 과거 설정, 수신899/격리1 기록.
- `inputs/legacy9048/rejected.jsonl`: GT 선택지 누락 1건.
- `results/legacy9048/`: 899개 고정 입력·파서 비교·요청 해시.
- `results/legacy9048_diagnostics/diagnostics.json`: H1/H3 집계.
- `results/legacy9048_diagnostics/h1_joint_disagreements_blind.jsonl`: 육안 검토 49개, GT/파서 출력 없음.
- `results/legacy9048_judge/pilot30_summary.json`: API 30건 종료 시점 집계.
- `results/legacy9048_judge/judge_results.jsonl`: 공통 Judge 캐시.
- `results/legacy9048_pilot30_scores.json`: API 미완료를 구분한 병합 결과. 주 비교 정책의 최종 정확도는 null이다.

`legacy_adapter.py --quarantine-invalid`는 무효 입력을 별도 파일로 남기고 legacy-pilot으로만 처리한다. 무효 입력을 조용히 수정하거나 HF 전량 조건을 완화하지 않는다. `pilot_diagnostics.py`는 저장된 비교 결과만 집계하며 API를 호출하지 않는다.
