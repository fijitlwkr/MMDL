# 기존 TSV pilot의 증거 자료

이 폴더는 과거 출력 cap 9048·생성 seed 42의 실험 기록입니다. 최종 HF/seed3407/cap8192 결과가 아닙니다.

| 폴더/파일 | 내용 |
|---|---|
| `h1/` | Qwen–MMMU 불일치 49건 원문 export, 반환 라벨, 문항별 비교, 집계, 보고서 |
| `h2/` | 자동 채택 표본 100건 원문 export, 305건 모집단 ID·표본 선정 정보, 반환 라벨, 집계, 보고서 |
| `PILOT_899.md` | 899건 파서 비교·length 진단·API30건 시험 당시 기록 |
| `*_original.md` | 당시 계획·입력 규격·Judge 운영 기록 원문 |

## 각 검토 폴더의 파일

- `source_export.json`: 당시 export의 원본 JSON 바이트. H2는 전달용 압축 텍스트를 풀었으며 원본 SHA-256이 같습니다.
- `export_manifest_original.json`: 당시 검토 자료의 manifest. 채팅용 분할본·ZIP 등 이번에 포함하지 않은 파일의 해시도 남아 있습니다. 현재 업로드 목록은 상위 `bundle_manifest.json`이 기준입니다.
- `returned_review_original.json`: 사용자 반환 파일의 원본 바이트.
- `human_labels_full.jsonl`: 원문·선택지와 반환 라벨 결합. GT/파서 정보가 있을 수 있어 새 블라인드 라벨러에게 그대로 주지 않습니다.
- `parser_comparison.jsonl`, `summary.json`, `REPORT.md`: 당시 고정 파서로 검증·집계한 기록.
- H2 `review_template_original.json`: 재사용한 H1 10건을 확인하는 최초 반환 양식.

H1 보고서의 ‘H2 검토가 남아 있다’ 등은 H1 집계 당시 상태입니다. 최신 완료 상태는 [SUMMARY.md](../SUMMARY.md)를 봅니다. 과거 보고서·JSON의 날짜와 수치, 라벨을 소급 수정하지 않았습니다.

## 재현 범위와 경로 변경

공개용 import 스크립트는 원래의 답 추출·라벨 검증·집계 로직을 유지하고 입력 경로를 인자로 받게 수정했습니다. H2 source는 압축 전달 문자열 대신 동일 바이트의 JSON을 읽습니다. 파서와 vendor는 원본 바이트 그대로입니다.

과거 `summary.json`의 `code_sha256`에는 당시 로컬 상대 경로와 import 스크립트 해시가 남아 있습니다. 새 실행 결과의 import 스크립트 해시/경로는 달라지지만 입력 해시·파서 해시·집계·문항별 라벨/비교 결과는 동일해야 합니다. `reproduce_reviews.py`는 이 차이만 제외하고 비교합니다.

전체 899건 생성 원문과 API30건 캐시는 이 업로드에 없습니다. 따라서 899건 Judge 대상 감소 및 API 비용은 당시 보고서를 인용하고, 이번 묶음만으로 전량을 재집계했다고 표현하지 않습니다. H1/H2 검토군은 원문·라벨이 포함되어 API 없이 재집계할 수 있습니다.
