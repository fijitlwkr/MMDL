# 업로드 검증 — 2026-09-19

- Python 표준 라이브러리 기반 소프트웨어 검사 **39개 통과**.
- `reproduce_reviews.py --evidence legacy_pilot --out <새 폴더>` 통과.
- H1: 49건 검증, Qwen 일치47 / MMMU 일치2 / hybrid 일치47·오독1·Judge1.
- H2: 100건 검증, 일치100 / 오독0; Qwen 추가 구제59 / 기존 성공41. Wilson 구간도 기존 집계와 동일.
- 각 군의 반환 원본·`human_labels_full.jsonl`·`parser_comparison.jsonl`이 기존 파일과 **바이트 단위 일치**.
- summary는 공개용 import 스크립트 경로·해시 항목만 제외하고 원래 집계와 일치.
- 고정 parser/vendor·source export·반환 라벨은 변경하지 않음. 전체 묶음의 SHA-256은 `bundle_manifest.json`에 기록.
- 이번 포장·검증 중 API 호출·모델 추론 없음.

이는 파일 무결성과 기존 H1/H2 집계 재현 검증입니다. 사람 판정의 독립 검증, Judge 정확성, 최종 HF baseline 채점 완료를 뜻하지 않습니다.
