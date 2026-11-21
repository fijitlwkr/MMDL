# 가설 B 후속 실험: 자기 응답 기반 학습 (DPO · SFT · 증류 · 병합)

Qwen3-VL-4B-Instruct(M0)의 **자기 샘플 응답**을 재료로 한 파인튜닝 실험의 코드·설정·데이터 목록이다.
결과는 [`results/hypB_eval/`](../../results/hypB_eval/README.md)(MMMU validation)와 [`results/hypB_dev/`](../../results/hypB_dev/README.md)(개발 세트)에 있다.

## 공통 조건

| 항목 | 값 |
|---|---|
| 기반 모델 | `Qwen/Qwen3-VL-4B-Instruct` rev `ebb281ec70b05090aa6165b016eac8ec08e71b17`, bf16 |
| 학습 범위 | LoRA r16 / α32 / dropout 0.05, 언어 모델 36층 q/k/v/o/gate/up/down (252모듈). 시각 인코더·merger 고정 |
| 문항 풀 | 외부 공개 데이터(MMFineReason 등)에서 고른 1,500문항 (`data/r1_pool.jsonl`). MMMU / MMMU-Pro 문항 없음 |
| 개발 세트 | 풀에서 층화 추출한 300문항 (`data/d3_dev.jsonl`, `data/d3_split.json`). 학습에 쓰지 않음 |
| M0 샘플링 | 문항당 4회, 평가와 같은 생성 조건 (vLLM 0.11.0, temperature 0.7, top_p 0.8, top_k 20, presence_penalty 1.5, max_new_tokens 8192, max_model_len 16384) |
| 보상 | 정답 일치 규칙 채점 `scripts/reward_v2.py` (Judge 없음) |
| 평가 | 저장소 `code/`의 baseline 평가 파이프라인 그대로 (MMMU validation 900문항, 채점 `hybrid100_mc_qwen_ab_open_no_length_gate_v2`) |

## 실험 목록

| 이름 | 방법 | 학습 데이터 | 주요 설정 | 설정 파일 |
|---|---|---|---|---|
| D1 | DPO (M0에서 시작) | M0 응답 쌍 707개: chosen = 정상 종료 정답, rejected = 잘림 / 오답 / 추출 실패 | lr 5e-6, β 0.1, rpo_alpha 1.0, 2 epoch (90 step) | `configs/d1_full/` |
| D2' | DPO (D1에서 시작) | D1 응답 쌍 696개, 같은 규칙 | D1과 같음 (88 step) | `configs/d2p_full/` |
| D3-e1 / D3-e2 | DPO (M0에서 시작) | 기본 쌍 561개(개발 문항 제외) + 간결 쌍 50개(4회 모두 정답인 문항에서 짧은 정답 > 긴 정답) = 611쌍 | lr 2e-5, β 0.1, rpo_alpha 1.0. e1 = 1 epoch(39 step), e2 = 2 epoch(78 step) | `configs/d3_e1/`, `configs/d3_e2/` |
| SD1-a / b / c | 자기 정답 응답 SFT | M0의 정상 종료 정답 응답 2,002개 | a: lr 2e-5, 2 epoch / b: lr 1e-4, 1 epoch / c: lr 1e-4, 2 epoch | `configs/sd1_*/` |
| C1-h / C1-f | 자기 증류 (합의 풀이 조건부 교사) | 1,036문항 × M0 응답 4개 = 4,144개. 교사 = 같은 M0에 기준 정답 풀이 하나를 추가로 보여 준 입력, 학생 = 평가 형식 입력 | 전체 어휘 Jensen-Shannon 손실, lr 1e-5 constant, 1 epoch(259 step). h = step 130, f = step 259 | `scripts/c1_config.json`, `configs/c1_*`, `configs/c1_full_run/` |
| T1 진단 | 학습 없음. M0를 temperature 0.35 / 0.10으로 개발 세트 측정 | — | 온도 외 조건 동일 | `scripts/t1_sample_dev.py` |
| AB1 | 가중치 병합: M0 + ΔD3-e1 + Δ(가설 A GRPO pilot step30) | — | 1:1 합, PEFT safe merge 순서(D3-e1 → A) | `scripts/ab1_merge_v2.py` |

- E1 / E2 / E3(외부 교사 풀이 SFT)의 학습 코드는 `exp/hypB-data` 브랜치 `assignment/experiments/hypB_train/`에 있다. E3 평가 결과는 이 브랜치의 `results/hypB_eval/E3_seed_3407/`에 있다.
- 개발 세트 후보 선택 규칙(전체 정답 수, M0가 4회 모두 맞힌 층의 정답 수)은 `scripts/sd1_select.py`, `scripts/c1_select.py`, `scripts/ab1_select.py`에 있다.

## 폴더

| 경로 | 내용 |
|---|---|
| `scripts/` | 샘플링(`sample_m0.py`, `d3_sample_dev.py`), 보상(`reward_v2.py`), 쌍 구성(`build_dpo_pairs.py`, `d3_prepare_v2.py`), 학습(`dpo_train.py`, `sd1_train.py`, `c1_train.py`), 병합(`ab1_merge_v2.py`), 선택(`*_select.py`) 등 |
| `scripts/frozen_generation/`, `scripts/frozen_v2/` | 평가와 같은 생성·채점 코드의 고정 사본 |
| `configs/<모델>/` | 학습 인자(`args.json`), adapter 설정, 학습 기록(`trainer_state.json`). 가중치는 포함하지 않음 |
| `data/` | 문항 풀, 개발 세트 분할, 학습 쌍·SFT 예제 목록(index). 응답 원문이 담긴 학습 파일은 HF에 둔다 |

## Hugging Face (비공개)

| 저장소 | 내용 |
|---|---|
| `MMDL-team4/hypB-d3e1-dpo` | D3-e1 LoRA adapter |
| `MMDL-team4/hypB-d1-dpo`, `MMDL-team4/hypB-d2p-dpo` | D1, D2' LoRA adapter |
| `MMDL-team4/hypB-rl-data` | 문항 풀, M0·D1 샘플, DPO 쌍, SFT·증류 학습 파일, 추가 이미지 |
| `MMDL-team4/hypB-eval-raw` | validation 생성 raw와 채점 결과 |

## 실행 환경

- 학습: A100 80GB, torch 2.8.0+cu128, transformers 4.57.1, peft 0.17.1, ms-swift 3.12.3
- 생성·평가: RTX 4090(validation), A100(개발 세트), vLLM 0.11.0
