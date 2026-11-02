# 가설 B 학습 실행 (Jinho)

이 디렉터리는 가설 B(Hypothesis B) 모델 E1 및 E2 학습을 위한 작업 공간입니다.
Linux GPU 서버(RunPod RTX 6000 Ada / L40S, 48GB VRAM)에서 실행합니다.

## 디렉터리 구성
- `train_config.json`: 고정된 ms-swift LoRA 학습 하이퍼파라미터
- `pilot_expected.json`: 파일럿 단계 토큰 경계/수치 검증용 기준값 (rows 0, 1, 2, 1161)
- `setup_gpu.sh`: 가상환경 `.venv-train` (ms-swift 3.12.3) 및 `.venv-eval` (vLLM 0.11.0) 생성 스크립트
- `resume_data.py`: HF 데이터셋(`MMDL-team4/hypB-train-data` v1.1) 캐시 확인 및 안정적 다운로드
- `check_cpu.py`: 모델 토크나이저 및 swift 전처리 검증 (CPU)
- `train.py`: 단일 GPU 학습 기본 스크립트
- `pilot.py`: 20-step 파일럿 검증 스크립트 (메모리, 시간, 파라미터 모니터링)
- `full.py`: 188-step (1 epoch) 본학습 스크립트
- `merge.py`: 학습된 LoRA adapter를 원본 베이스 모델에 병합하는 스크립트
- `check_vllm.py`: 병합된 모델이 vLLM 0.11.0 엔진에서 정상 로딩되는지 검증
- `upload_hf.py`: 산출물(adapter, log, config)을 Hugging Face의 `run-jinho` 브랜치로 업로드

## 실행 요약
자세한 단계별 실행 가이드는 프로젝트 루트의 `TASK.md`를 참고하세요.

