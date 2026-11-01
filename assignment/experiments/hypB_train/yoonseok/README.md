# 가설 B 학습 실행

Linux GPU 서버에서 이 디렉터리를 기준으로 실행한다. 학습은 Python 3.12, ms-swift 3.12.3, 평가 로딩은 별도 vLLM 0.11.0 환경을 사용한다. 가설 A의 원격 브랜치 `exp/hypA-omr-data`에는 학습 설정이 없어 PLAN 2-1과 main의 `code/common.py`, `inputs.py`, `config.yaml`을 기준으로 했다.

```bash
bash setup_gpu.sh
# HF 로그인은 사용자가 직접 마친 상태여야 한다.
.venv-train/bin/python resume_data.py
DATA=$(.venv-train/bin/python -c 'from huggingface_hub import snapshot_download; from pathlib import Path; p=Path(snapshot_download("MMDL-team4/hypB-train-data", repo_type="dataset", revision="v1.1")); assert p.name == "1833bac3be047aa8bd146492436323bb7c14092a"; print(next(p.rglob("E1_train_swift.jsonl")).parent)')
PROCESSOR=$(.venv-train/bin/python -c 'from huggingface_hub import snapshot_download; from train import CONFIG; print(snapshot_download(CONFIG["model"], revision=CONFIG["model_revision"], allow_patterns=["*.json", "*.txt", "*.jinja"]))')
.venv-train/bin/python check_cpu.py "$DATA" "$PROCESSOR"
```

파일럿 승인 후에만 다음 명령을 실행한다. 한 GPU만 노출한다. `artifacts/` 아래에 매번 새 출력 폴더를 지정한다.

요청 제한이 있는 파드에서는 먼저 `.venv-train/bin/python resume_data.py`로 기존 캐시를 이어받는다. 누락 파일을 순차 다운로드하고 파일마다 0.5초 대기하며, 429 발생 시 310초 대기 후 재시도한다.

```bash
.venv-train/bin/python pilot.py E1 pilot "$DATA" artifacts/pilot
.venv-train/bin/python merge.py artifacts/pilot/checkpoint-20 artifacts/merged-pilot
.venv-eval/bin/python check_vllm.py artifacts/merged-pilot
```

네 실행에 같은 seed 3407 순열을 사용한다. 원본 행 1161이 처음 320개 밖에 있으면 320번째 행과 맞바꾸고 추가 셔플은 끈다. 따라서 원본 3,000행이 한 번씩 포함되고 20번째 업데이트에서 최장 입력을 처리한다. 파일럿과 본학습 옵션 차이는 최대 step과 평가 간격뿐이다. 20 step 통과 및 별도 승인 후 각 모델에 `train.py E1 full`, `train.py E2 full`을 같은 인자 형식으로 호출한다. 출력 폴더는 각각 새로 지정한다. 마지막 체크포인트를 동일한 절차로 병합·로딩한다.
