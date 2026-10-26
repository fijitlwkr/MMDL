# OMR 데이터 준비와 MMMU 중복 검사 (가설 A)

가설 A 학습 데이터 중 의료 몫을 OpenMedReason(`neginb/OpenMedReason`)에서 고르고, 학습 이미지가 MMMU 시험 이미지와 겹치지 않는지 확인하는 스크립트다. 만든 데이터는 레포에 두지 않고 HF 데이터셋 `MMDL-team4/hypA-train-data`의 `incoming/omr/`에 올렸다(만든 방법과 통계는 그 안의 `stats.md`).

## 순서

| 단계 | 스크립트 | 결과 |
|---|---|---|
| 1. MMMU 이미지 지문 색인 | `build_mmmu_phash.py` | `mmmu_phash.csv` (MMMU dev/val/test + MMMU-Pro 19,041장, 레포에 포함) |
| 2. 그림 읽기 질문 후보 뽑기 | `omr_select.py`, `omr_topup.py` | `candidates*.csv` |
| 3. MMMU 중복 검사 | `compare_phash.py` | `contamination_report*.csv` (해밍 거리 ≤ 8 제외, 9~12 확인) |
| 4. 정답 종류·거부 응답·같은 그림 거르기 | `build_selection.py` | `selection.csv` |
| 5. 눈 검수(선택) | `review_omr.py` | 로컬 검수 앱 |
| 6. 이미지 없이 풀기 입력 만들기 | `build_filter_input.py` | `filter_input.csv` |
| 7. 이미지 없이 풀기 필터 (GPU) | `text_only_filter.py` | `filter_result.csv` (4B 가 3번 중 2번 이상 맞히면 drop) |
| 8. 최종 문항 고르기 | `finalize_omr.py` | `final/omr_600.jsonl`, `final/omr_1500.jsonl` |
| 9. 대조군 | `omr_control.py` | `final/control_1500.jsonl` |
| 10. 팀 형식 변환·검증 | `make_upload.py` | `omr_e1_*.jsonl`, `omr_control_*.jsonl`, `images/`, `stats.md` |
| 11. HF 업로드 | `upload_hf.py` | 요청 한도에 걸리면 쉬었다가 이어서 올림 |

각 스크립트 맨 위 설명에 사용법이 있다. 경로는 모두 인자로 받는다. 7번은 팀 `code/config.yaml` 의 모델 revision·샘플링 값을 읽는다.

## 다른 데이터의 MMMU 중복 검사

후보 CSV 에 이미지마다 pHash(16자리 hex) 열이 있으면 이미지를 받지 않고 바로 비교할 수 있다. Honey-Data-V2 카드의 `image_phashes` 는 `imagehash.phash(8×8)` 와 같은 값이다(25장 비교, 전부 일치). 이미지가 여러 장인 행은 한 장씩 한 줄로 풀어서 넣는다.

```bash
python compare_phash.py --index mmmu_phash.csv --candidates <후보 CSV> --out <결과 CSV> --phash-col image_phashes
```

## 설치

`requirements.txt` 참고. 7번만 GPU 환경이 따로 필요하다.
