# 가설 B 학습 계획

실행 전 고정. 결과를 본 뒤 설정을 바꾸지 않는다. 동작 문제로 바꾸는 경우만 변경 기록에 남긴다.

## 1. 목표

E1·E2 두 모델을 같은 설정으로 학습하고, 평가에 바로 쓸 수 있는 상태로 보관한다.

| 모델 | 학습 데이터 |
|---|---|
| E1 | MMFR 정리 풀이 + Final Answer, 3,000문항 |
| E2 | 같은 3,000문항, Final Answer 한 줄만 |

## 2. 학습 조건

| 항목 | 값 |
|---|---|
| 모델 | Qwen3-VL-4B-Instruct, revision `ebb281ec…`, bf16 |
| 데이터 | HF `MMDL-team4/hypB-train-data` v1.1 (커밋 `e9fe258b`, E1·E2 각 3,000, holdout 299). ms-swift 형식 파일 사용 |
| 학습 도구 | ms-swift (가설 A와 동일) |
| 학습 범위 | 언어모델 LoRA만. 시각 인코더·merger 고정 |
| LoRA | r 16, α 32, attention·MLP 전부 (언어모델 36층) |
| 최적화 | lr 1e-4, cosine, warmup 3%, 1 epoch, 유효 배치 16 (약 188 step) |
| 손실 | 모델 응답 부분만 |
| 학습 입력 | 이미지 해상도·프롬프트·이미지 배치를 평가(GitHub main 기준)와 같게 |
| seed | 3407 |
| 시작점 | E1·E2 모두 원본 모델에서 각각 시작 |
| GPU | 48GB급 (RTX 6000 Ada, 없으면 L40S) |

E1과 E2는 데이터 파일만 다르고 나머지는 모두 같다.

### 2-1. 세부 설정

| 구분 | 항목 | 값 | 비고 |
|---|---|---|---|
| 모델 | 정밀도 | bf16 | 학습·병합 모두 |
| | attention 구현 | sdpa | flash-attn 설치 없이 |
| | chat template | Qwen3-VL 기본, system prompt 없음 | 평가와 동일 |
| LoRA | rank / alpha / dropout | 16 / 32 / 0.05 | |
| | 대상 모듈 | q_proj, k_proj, v_proj, o_proj, gate_proj, up_proj, down_proj | 언어모델 36층만 |
| | 고정 | 시각 인코더(ViT), merger(DeepStack 포함) | |
| | bias / modules_to_save | 없음 / 없음 | |
| 최적화 | optimizer | AdamW (β1 0.9, β2 0.999, ε 1e-8) | 도구 기본값, 파일럿에서 확인 |
| | learning rate | 1e-4 | |
| | scheduler / warmup | cosine / 3% (약 6 step) | |
| | weight decay | 0 | |
| | gradient clipping | 1.0 | 도구 기본값, 파일럿에서 확인 |
| | epoch | 1 | |
| 배치 | 장치당 배치 | 1 | |
| | gradient accumulation | 16 | 유효 배치 16 |
| | 총 step | 약 188 (3,000 ÷ 16) | |
| 메모리 | gradient checkpointing | 켬 | |
| 길이 | 최대 길이 | 8,192 토큰 | 데이터 최대 4,905, 잘리는 문항 없음 |
| 손실 | 손실 범위 | assistant 응답 토큰만 (질문·이미지 제외) | |
| 이미지 | min_pixels / max_pixels | 1,003,520 / 4,014,080 | 이미지당 약 980~3,920 토큰, 평가와 동일 |
| | 이미지 위치 | 텍스트 앞 | 평가와 동일 |
| 데이터 | 학습 / 점검 | E1 또는 E2 3,000 / holdout 299 | holdout은 학습에 넣지 않음 |
| | 순서 | 매 실행 seed 3407로 섞음 | |
| | 자동 분할 | 사용 안 함 (학습 데이터를 점검용으로 떼지 않음) | |
| 기록 | loss 기록 | 매 step | |
| | holdout loss | 60 step마다 (본학습), 10 step마다 (파일럿) | 점검용 |
| | 저장 | 마지막 체크포인트만, adapter만 | 중간 저장 없음 |
| seed | 학습·데이터 | 3407 | |
| 파일럿 | 최대 step | 20 | 본학습과 다른 것은 이것뿐 |

## 3. 진행 순서

### 3-1. 준비
- 데이터 브랜치 `exp/hypB-data`에 이어서 작업한다. 학습 파일은 사람별 폴더 `assignment/experiments/hypB_train/<이름>/`에 둔다.
- 가설 A와 학습 설정을 맞춘다 (이미지 해상도 지정, 응답만 loss, 시각 쪽 고정).
- 학습 스크립트를 작성한다.

### 3-2. 환경 구성
- GPU를 빌리고 학습 환경을 만든다.
- 모델(고정 revision)과 데이터(v1.1)를 받는다.

### 3-3. 파일럿 (20 step) — 하나라도 실패하면 본학습 중단 후 상의

| # | 확인할 것 | 통과 조건 |
|---|---|---|
| 1 | 학습되는 파라미터 | 언어모델 LoRA만. 시각 인코더·merger는 0개 |
| 2 | 손실 범위 | 응답 부분에만 걸림 |
| 3 | 학습 이미지 해상도 | 평가와 같음 (미리 계산한 이미지 토큰 수와 일치) |
| 4 | 질문 속 `<image 1>` 글자 | 이미지 자리로 오인되지 않음 (전체 길이 일치) |
| 5 | 메모리·시간 | 가장 긴 행(1161)을 넣은 step까지 OOM 없음, 최대 VRAM 기록, step 시간으로 본학습 시간 추정 |
| 6 | 병합 | 학습한 LoRA를 합친 모델이 정상 저장되고 평가 환경에서 로딩됨 |

비교 기준값은 `pilot_expected.json`에 미리 계산해 두었다.

### 3-4. 본학습
- E1, E2를 학습한다.
- 기록: train loss, holdout loss, 소요 시간, 메모리.
- holdout loss는 점검용이다. 이를 보고 설정이나 체크포인트를 고르지 않는다 (마지막 체크포인트 사용).

### 3-5. 마무리
- 두 모델을 병합하고 processor·chat template이 원본과 같은지 확인한다.
- adapter와 학습 기록을 5절 위치에 보관한다.

## 4. 완료 기준

- E1·E2 adapter가 각 HF 저장소에 올라가 있음
- 파일럿 확인 결과, 학습 로그, 설정이 브랜치에 기록돼 있음

## 5. 보관 위치

| 무엇 | 어디에 |
|---|---|
| 데이터 선별 규칙·스크립트·문항 목록 | GitHub `exp/hypB-data` (커밋 `44c7449`, push 완료) |
| 학습 스크립트, 설정, 파일럿 결과, 학습 로그 | GitHub `exp/hypB-data`의 `assignment/experiments/hypB_train/<이름>/` (사람별 폴더) |
| E1 LoRA adapter, 학습 설정 기록 | HF 비공개 모델 저장소 `MMDL-team4/hypB-e1-structured-3k`, 브랜치 `run-<이름>` |
| E2 LoRA adapter, 학습 설정 기록 | HF 비공개 모델 저장소 `MMDL-team4/hypB-e2-answer-3k`, 브랜치 `run-<이름>` |
| 병합 모델 (약 9GB) | 필요할 때만. 기본은 평가 때 원본 + adapter로 병합 |

- 저장소 이름은 가설 A 규칙(`hyp{가설}-e{번호}-{설명}-{규모}`)과 맞췄다. 두 저장소와 README(학습 전 상태)는 만들어 두었다.
- 학습 후 README의 기록 칸(Git 커밋, 패키지 버전, GPU, 학습 시간)을 채운다.
- main 브랜치는 비워 두고, 평가에 쓸 결과가 정해지면 main에 올리고 `v1.0` 태그를 붙인다.
- HF 컬렉션 `Hypothesis B`(비공개)에 `hypB-train-data`, `hypB-e1-structured-3k`, `hypB-e2-answer-3k`를 넣어 두었다.

## 6. 지키는 것

- MMMU / MMMU-Pro 문항은 학습에 쓰지 않는다.
- 데이터·모델은 GitHub에 커밋하지 않는다.
- GPU 사용 전에 확인한다. 예상 GPU 3~5시간 (환경 1h + 파일럿 1h + 학습 각 1~2h).

## 변경 기록

- HF snapshot의 JSONL symlink 이름을 보존하도록 check_cpu.py의 데이터 경로를 absolute()로 처리한다. resolve()는 확장자 없는 blob 경로가 되어 파일 형식 판별이 실패했다 (2026-11-01 파드 점검).
- E1 기준값 +1 수정: 기준값을 전체 대화 한 번에 토큰화해 계산했는데, 평가 시 입력은 프롬프트 끝 198에서 끊기므로 경계 분리 토큰화가 맞음
