# 실험 디렉터리 운영

공유 구현은 저장소 루트의 `run_mmmu_eval.py`, `mmmu_pipeline/`, `requirements.txt`에 둔다.
각 실험 디렉터리는 설정, 실행 래퍼, 해당 실험의 출력만 소유한다.

## 새 실험 디렉터리 체크리스트

1. `experiments/expA_<name>/`처럼 실험을 식별할 수 있는 새 디렉터리를 만든다.
2. `exp0_baseline/config.json`과 `exp0_baseline/run.sh`만 복사한다. 기존 `outputs/` 내용은 복사하지 않는다.
3. 빈 `outputs/` 디렉터리를 만든다.
4. `config.json`의 `output_dir`은 `outputs`로 유지한다. 이 값은 config 파일 위치를 기준으로 해석된다.
5. baseline과 다른 설정을 실험할 때 `enforce_fixed_baseline`을 `false`로 바꾸고, 변경 변수와
   `output_dir` 외의 설정이 의도대로 유지됐는지 diff로 확인한다.
6. `run.sh`의 `SCRIPT_DIR`, `REPO_ROOT`, `CONFIG_PATH`, `OUTPUT_DIR` 계산을 유지한다. 스크립트 안에서
   호출자의 CWD를 전제로 한 상대경로를 추가하지 않는다.
7. 실행 전 `config.json`을 로드해 resolve된 `output_dir`이 새 실험 디렉터리 아래인지 확인한다.
   새 디렉터리의 `run.sh --dry-run`으로 확인할 수 있다.
8. 실행 전 `outputs/`가 비어 있는지 확인하고, 실행 후 raw generation, 환경 snapshot, 결과 표를
   함께 보관한다.
9. 변경한 변수, 실행 시각, 모델·데이터 revision을 실험 문서 또는 제출 기록에 남긴다.

예시 생성 명령:

```bash
mkdir -p experiments/expA_<name>/outputs
cp experiments/exp0_baseline/config.json experiments/expA_<name>/config.json
cp experiments/exp0_baseline/run.sh experiments/expA_<name>/run.sh
```

`run.sh`는 저장소 루트에서 실행할 필요가 없다. 어느 CWD에서 호출해도 자기 파일 위치를 기준으로
공유 runner와 config를 찾는다.
