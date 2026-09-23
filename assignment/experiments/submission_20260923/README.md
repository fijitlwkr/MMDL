# 제출 보고서용 채점 결과와 근거 — 2026-09-23

최신 수신 `max_new_tokens8192_hakyung`의 900문항을 **length 게이트 없는 v2 + GPT-4.1-mini**로 채점한 결과다. **600/900(66.67%)**, 객관식 560/847, 주관식 40/53, API 미완료 0건이다. 팀의 baseline 승격을 선언하는 문서는 아니다.

- [과제 보고서](../../../reports/mmmu_baseline.md): 4절 채점 방식, 5·6절 점수, 7절 격차 분석, 8절 검증 범위.
- [파서 선택과 격차 분석의 실험 근거](EVIDENCE.md): 주장별 실험 조건·관측값·근거 파일.
- [30과목 결과표](results/subject_scores.md), [집계 JSON](results/scores.json), [900문항별 정오](results/item_results.jsonl).
- [정책 비교 집계](results/comparisons.json), [length 경로 변경 문항](results/changed_items.jsonl).

## API 없이 재현

저장소 루트, Python 3.10 이상에서 평가 도구의 의존성을 설치한다.

```bash
python -m pip install -r assignment/experiments/raw_evaluation/requirements.txt
```

아래 **한 명령**으로 원본·캐시를 검증하고 900문항 채점, 과목별 표, 비교 실험을 재계산해 제출 결과와 대조한다. 출력 폴더는 새 빈 경로를 사용한다.

```bash
python assignment/experiments/submission_20260923/reproduce.py --out assignment/experiments/raw_evaluation/outputs/submission_check --expected assignment/experiments/submission_20260923/results
```

API 키나 GPU가 필요하지 않다. 저장된 Judge 응답만 사용하며 새로운 API 호출·모델 추론은 하지 않는다. 이 명령은 **저장 응답의 채점 재현**이다. 모델 재추론부터 채점까지 연결하는 통합 실행 명령은 추론팀 작업과 통합해야 한다. 새로 추론한 응답에는 이 캐시를 그대로 적용하지 않는다.

## 입력과 판정의 연결

| 파일 | 용도 |
|---|---|
| `input/raw.jsonl` | 실제 추론 900문항 원본. 문제 ID·prompt·선택지·gold·생성 텍스트·토큰·종료 사유 포함 |
| `input/run_metadata.json` | 수신 당시 모델·데이터 revision, 생성·이미지·환경 설정 및 raw 해시 |
| `input/scoring_config.yaml` | 이번 채점에 고정한 v2 정책과 Judge 모델·파라미터. 과거 추론 설정의 증거는 run_metadata를 사용 |
| `judge/gpt-4.1-mini.jsonl` | 같은 raw의 기존 Judge 응답 363개. v2에서 345개를 사용하고 나머지 18개는 게이트 비교에 사용 |
| `judge/gpt-4o-mini.jsonl` | 같은 raw·게이트 적용 정책의 비교 Judge 응답 363개 |
| `results/` | 재계산 가능한 과목별·문항별 결과와 통제 비교 |
| `reproduce.py` | 기존 평가 도구를 사용해 원본과 요청 해시를 검증하고 저장 응답으로 재집계 |

Raw SHA-256: `ef23f0c49d9b1ae6c62b9625fbd52cce474a0c035c1a644cfa737e0967daa313`.

입력과 메타데이터는 수신본을 바이트 그대로 보존했다. 추론팀 브랜치 `eval/mmmu-baseline-infer`의 `assignment/runs/max_new_tokens8192_hakyung/`에 있는 동명 파일과도 바이트가 같다. 기존 `assignment/runs/draft/raw.jsonl`과는 다른 실행이다. 그 이전 raw의 v2 점수 **608/900(67.56%)**를 이번 결과와 섞지 않는다.

객관식 `predicted`는 선택지 문자다. 주관식은 `A=참조답 원문`, `B=Other Answers`로 변환하므로 A/B는 자유형 답 문자열을 그대로 추출한 값이 아니다. 문항별 정오는 이 채점 정책의 판정이며 사람 검증 완료 라벨이 아니다. 최종 추출 실패 36건도 오답 300건에 포함한다.

## 비교 실험을 읽는 방법

- 같은 raw에서 게이트 적용 4.1-mini **594/900**, 제거 **600/900**: 채점 경로만 바꾼 비교.
- 같은 raw·게이트 적용 정책에서 4.1-mini **594/900**, 4o-mini **567/900**: Judge 모델만 바꾼 비교.
- MMMU 규칙 단독 **452/900**과 v2 **600/900**: 파서·주관식 처리·Judge 사용이 함께 다른 파이프라인 비교.
- 기존 H1/H2 사람 검토는 [공개된 과거 실험](../scoring_lab/SUMMARY.md)에 있다. 현재 raw의 전량 추출 정확도 검증으로 해석하지 않는다.

원본 `run_metadata.json`에 기록된 실행 명령은 경로 중복이 있어 그대로 실행 가능한 명령으로 인용하지 않는다. 생성 설정·환경 수치는 원기록으로 보존하되 추론팀의 통합 실행 안내로 보완해야 한다. 보고서 1~3절 초안 역시 추론팀 브랜치에서 별도로 진행 중이다.
