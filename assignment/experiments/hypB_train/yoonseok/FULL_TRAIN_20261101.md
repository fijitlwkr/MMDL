# 가설 B 본학습 결과 · 2026-11-01

E1·E2를 순서대로 각각 고정된 원본 모델에서 새로 시작해 1 epoch, 188 step 학습했다. 두 실행 모두 adapters=[], resume_from_checkpoint=null이며 마지막 checkpoint-188을 사용했다.

## 학습과 환경

- 학습 코드 Git 커밋 b54e00d2ae9e91cc5a93641b4d2da0551cfa93dd
- 사전 파일럿 결과 커밋 695e1384684fcd415014998f9fd950f9905304a6은 pull 후 exp/hypB-data에 push했다.
- GPU NVIDIA RTX 6000 Ada Generation, 49,140 MiB
- 이미지 runpod/pytorch:1.0.2-cu1281-torch280-ubuntu2404, Python 3.12.3
- ms-swift 3.12.3, transformers 4.57.1, torch 2.8.0, peft 0.17.1, qwen-vl-utils 0.0.14
- 평가 환경 vLLM 0.11.0. 실제 전체 패키지 목록은 각 결과 폴더의 packages_train.txt와 packages_eval.txt에 보관했다.
- 원본 모델 Qwen/Qwen3-VL-4B-Instruct, revision ebb281ec70b05090aa6165b016eac8ec08e71b17, bf16
- 데이터 MMDL-team4/hypB-train-data v1.1. 태그 객체 e9fe258b9d044e0693441a4c54138054d19130ab → 실제 커밋 1833bac3be047aa8bd146492436323bb7c14092a

파일럿과 같은 공통 설정을 사용하고 max_steps=-1, num_train_epochs=1, eval_steps=60으로 본학습했다. 언어모델 LoRA 252모듈·504개 A/B 텐서만 학습되고 시각 쪽 학습 파라미터는 0개임을 실제 모델에서 확인했다. AdamW betas 0.9/0.999, eps 1e-8, weight decay 0도 확인했다.

학습 계측 callback은 기존 파일럿 계측을 재사용하고 기대 완료 step을 188로 검사했다. 모든 원격 명령은 HF_HOME=/workspace/hf_cache를 사용했다.

## 최종 수치

학습 시간에는 holdout 평가와 마지막 저장이 포함된다. End-to-end 시간은 모델 초기화와 데이터 준비도 포함한다.

| 항목 | E1 | E2 |
|---|---:|---:|
| epoch / step | 1 / 188 | 1 / 188 |
| 학습 시간 | 3,378.85초, 56분 18.85초 | 2,414.86초, 40분 14.86초 |
| End-to-end 시간 | 57분 41초 | 41분 |
| Epoch 평균 train loss | 0.44173074 | 0.47716622 |
| 마지막 step train loss | 0.35753852 | 0.11738076 |
| 최종 holdout loss, step 188 | 0.38542396 | 0.79168916 |
| 평균 학습 step, 평가 제외 | 15.22초 | 10.27초 |
| GPU 최대 사용량, 1초 샘플링 | 46,311 MiB | 44,628 MiB |
| 마지막 adapter 크기 | 132,195,448B | 132,195,448B |

## Holdout 기록

| step | E1 loss | E2 loss |
|---:|---:|---:|
| 60 | 0.40827620 | 0.79335374 |
| 120 | 0.38946667 | 0.79026783 |
| 180 | 0.38543236 | 0.79167110 |
| 188 | 0.38542396 | 0.79168916 |

ms-swift 3.12.3의 DefaultFlowCallbackNew는 마지막 step에서도 평가·저장을 수행한다. 따라서 60 step 간격 평가 외에 188 step 평가가 자동 추가됐다. 그 값을 최종 holdout loss로 기록했다. holdout 결과로 설정이나 체크포인트를 선택하는 작업은 없었다.

## 병합과 평가 환경 로딩

| 항목 | E1 | E2 |
|---|---|---|
| 사용 adapter | checkpoint-188 | checkpoint-188 |
| 병합 | 통과 | 통과 |
| 가중치 dtype / 총 크기 | BF16 / 8,875,719,328B | BF16 / 8,875,719,328B |
| 원본 processor·tokenizer·chat template 8개 파일 | 바이트 일치 | 바이트 일치 |
| vLLM 0.11.0 로딩 | 통과, 종료 코드 0 | 통과, 종료 코드 0 |
| vLLM 초기화 | 127.164초 | 128.641초 |

## HF 보관

| 실행 | 저장소 | 브랜치 | 커밋 |
|---|---|---|---|
| E1 | MMDL-team4/hypB-e1-structured-3k | run-yoonseok | 0de38ff61af238608dc7be53358f1dac23788995 |
| E2 | MMDL-team4/hypB-e2-answer-3k | run-yoonseok | 72e45c1bb07eb79179739fae949ccf80f21e891b |

adapter, 학습 설정, loss 기록·로그, 패키지 목록과 완료된 README를 업로드했다. 업로드된 adapter의 LFS SHA-256이 마지막 체크포인트와 일치함을 확인했다. 각 main 커밋의 전후 일치도 확인했다.

배포용 adapter_config.json의 base_model_name_or_path와 revision은 고정된 HF 원본 저장소 ID와 모델 revision으로 기록해 다른 환경에서도 원본을 찾을 수 있게 했다. 저장된 체크포인트의 원래 metadata는 각 결과 폴더의 adapter_config.json에, HF 배포 metadata는 hf_adapter_config.json에 따로 보관했다. 두 원본 참조 필드 이외의 LoRA 설정이 같음을 검사했다.

병합 모델은 파드에 보관한다. 커밋용 학습 로그에서는 데이터 예문 출력 4개를 제외했고 원본 로그는 파드 artifacts/full_20261101에 보관했다.

## 결과 파일

- full_E1_20261101/summary.json, full_E2_20261101/summary.json에 원본 모델·학습 시간·loss·검증 수치를 기록했다.
- 각 폴더의 train_log.txt, training_history.json, training_observations.json, train_args.json, trainer_state.json에 실행 기록이 있다.
- validation.json과 merge_log.txt·vllm_log.txt에 병합·로딩 근거가 있다.
- hf_upload.json과 HF_README.md에 업로드 커밋·파일 목록·모델 카드 기록이 있다.

원격 작업 경로는 /workspace/MMDL/assignment/experiments/hypB_train/yoonseok이다. 파드는 실행 상태로 남겨 두며 사용자가 직접 종료한다.
