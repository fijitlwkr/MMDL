# MMMU 채점 방식 실험 — 채윤석

**기존 저장 응답으로 수행한 H1·H2 실험과 재현 자료입니다. 최종 HF baseline이 아닙니다.**

- 기존 입력: TSV 기반 cap 9048, 생성 seed 42. 원본 900건 중 선택지 입력 오류 1건을 격리한 899건 pilot.
- H1: Qwen–MMMU 공동 추출 성공 316건 중 답 불일치 49건 검토. 검토 답과 Qwen 47/49, MMMU(no random) 2/49 일치.
- H2: Final Answer 자동 채택 305건 중 고정 무작위 표본 100건 검토. 100/100 일치, Wilson 95% 구간 96.30–100%. Qwen 실패를 보완한 59건도 모두 일치.
- H1/H2 중복 10건, 고유 139건. 반환 라벨은 단일 검토자의 `human_confirmed`이며 독립 2인 조정 결과가 아님.
- VLMEvalKit은 **중간 실험에서 추가 비교 필요성이 없어 후보에서 제외**. 코드·수치는 과거 비교 재현을 위해 보존.

## 먼저 읽을 자료

| 문서 | 내용 |
|---|---|
| [SUMMARY.md](SUMMARY.md) | H1·H2 결론, 권장 하이브리드, 오독 사례, 한계 |
| [PROTOCOL.md](PROTOCOL.md) | 가설·채택 판단과 최신 팀 계획의 구분 |
| [INPUT_CONTRACT.md](INPUT_CONTRACT.md) | draft 전달 시 필요한 입력과 현재 도구의 호환 범위 |
| [SHARED_JUDGE.md](SHARED_JUDGE.md) | 기존 공통 Judge 실행기와 캐시 명세 |
| [THIRD_PARTY.md](THIRD_PARTY.md) | 고정한 Qwen/MMMU/VLMEvalKit 출처·commit·라이선스 |
| [legacy_pilot/README.md](legacy_pilot/README.md) | 검토 근거와 과거 기록을 읽는 방법 |

## H1·H2 결과를 API 없이 재현

Python 3.10+ 표준 라이브러리만 사용합니다. 저장소 root에서:

```bash
cd assignment/experiments/scoring_lab
python reproduce_reviews.py --evidence legacy_pilot --out _reproduced
```

입력·라벨·파서 해시를 검사하고 H1/H2를 다시 집계합니다. 저장된 집계 및 문항별 결과와 같아야 성공합니다. 출력은 새 폴더에 쓰고 원본을 덮어쓰지 않습니다. API 키·GPU·재추론은 필요 없습니다. 다시 실행할 때는 `--out`에 새로운 경로를 지정합니다.

이 명령은 **첨부한 H1 49건·H2 100건 검토 결과의 재현**입니다. 899건 전체의 파서 비교 및 Judge 30건 시험을 새로 실행하는 명령은 아닙니다. 전체 pilot의 원본·API 캐시는 이 묶음에 포함되지 않았고, 해당 수치는 [당시 기록](legacy_pilot/PILOT_899.md)으로만 보존합니다.

## 코드 구성

- `parsers.py`, `vendor/`: 당시 고정 파서와 Final Answer 보완 규칙. 바이트 그대로 보존.
- `lab.py`: 저장 응답의 검증·정책별 비교·캐시 병합.
- `focused_review.py`, `pilot_diagnostics.py`: 검토 표본 선정과 파서·length 진단.
- `import_h1_review.py`, `import_h2_review.py`, `reproduce_reviews.py`: 반환 라벨 검증·재집계.
- `legacy_adapter.py`: 과거 TSV 로그의 명시적 변환과 오류 격리.
- `judge_runner.py`: 과거 실험의 공통 Judge 실행기. 기본 dry-run.
- `test_*.py`: 기존 소프트웨어 검사. 통과 여부와 실제 추출 정확도는 별개.
- `bundle_manifest.json`: 업로드 묶음의 파일별 SHA-256. `.gitattributes`는 checkout 시 줄바꿈 변환으로 해시가 바뀌지 않게 합니다.

```bash
python -m unittest discover -s . -p 'test*.py' -v
```

## 최신 팀 계획에 적용할 때

팀 최종 입력은 HF 고정 revision·생성 seed 3407·출력 cap 8192입니다. 이 묶음의 기존 결과를 그 조건의 점수로 옮겨 쓰지 않습니다. draft를 받으면 필드 변환과 채점 분기를 먼저 합의하고, 최종 raw가 고정된 뒤 별도 결과 디렉터리에서 검증합니다.

현재 보존한 실험 코드는 open 응답 일부를 참조답 A / Other Answers B로 바꾸는 과거 정책도 포함합니다. 팀에서 정한 `parse_open_response + eval_open`만으로 처리하는 최종 파이프라인과 완전히 같지 않습니다. 정상 종료 파싱 실패의 fallback 범위, 주관식 length, Final Answer 후보 채택, Judge 비교 여부는 [PROTOCOL.md](PROTOCOL.md)의 팀 반영 항목을 확인하세요.

`assignment/runs/*/raw.jsonl`은 읽기만 합니다. 실험 산출물은 이 폴더 아래 별도 run 경로에 보관하고, 추론팀 `assignment/src/`에서 이 폴더를 import하지 않습니다. 승인 후 채택한 평가 구현만 추론팀에 전달합니다.

## 확인된 한계

H1 Chemistry_18에서 기존 hybrid의 오독이 1건 남아 있습니다. `Final Answer: A or B.` 합성 반례도 해결하지 않았습니다. H2 100/100은 표본의 추출 일치 결과이며 MMMU 정답률이나 전체 평가 무오류를 뜻하지 않습니다. 파서 코드를 바꾸면 새 후보 버전으로 분리합니다.
