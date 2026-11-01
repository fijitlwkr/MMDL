# 가설 B 평가 2단계: 패키지 게이트 실패로 생성 전 중단

2026-11-01, 사용자 요청에 따라 RTX 4090 파드에서 환경을 구성했으나,
고정 패키지 게이트의 Torch 배포 버전 조건을 통과하지 못해 중단했다.
평가 코드·config.yaml·패키지는 실패 후 수정하지 않았다. Judge 호출은 0회이다.

## 완료한 작업

- 준비 커밋 ef13735027398c810d30cba057d08e0d76e517b9를 git pull 후 exp/hypB-data에 push하고 원격 해시를 확인했다.
- 파드 /workspace/MMDL에 exp/hypB-data를 clone했다. 실행 소스는 위 커밋이다.
- verify_code.py로 main 016b3cf558e3dd9e366b277f5f871b28092a1379 기준 고정 코드 40개를 확인했다.
- setup_gpu.sh 설치가 종료 코드 0으로 끝났고 pip check는 No broken requirements found였다.
  설치 시간은 약 3,953초(65분 53초)였다. 네트워크 볼륨의 파일 I/O 대기로 설치가 길어졌다.
- GPU: NVIDIA GeForce RTX 4090, 24,564 MiB, driver 595.91.07.
  이미지(사용자 지정): runpod/pytorch:1.0.2-cu1281-torch280-ubuntu2404.
- 기본 Python은 그대로 두고 /workspace/hypB-eval-env에 설치했다.
  모든 원격 작업에 HF_HOME=/workspace/hf_cache를 적용했다.
- 원본 ebb281ec70b05090aa6165b016eac8ec08e71b17 및 E1 adapter
  0de38ff61af238608dc7be53358f1dac23788995 다운로드를 마쳤다.
  E1의 별도 시험 경로 smoke_E1에서 병합 준비를 시작했지만 완료 전 중단했다.

## 실패 원인

| 검사 | 요구값 | 실측 |
|---|---|---|
| 고정 packages.expected_version: torch | 2.8.0+cu128 | 2.8.0 — FAIL |
| torch.__version__ | 진단용 | 2.8.0+cu128 |
| torch.version.cuda | 진단용 | 12.8 |
| pip check | 의존성 정상 | 정상 |

main code/check_env.py의 packages_section은 importlib.metadata.version("torch")를 읽어
config의 문자열과 정확히 비교한다. 현재 환경의 배포 메타데이터는 2.8.0이다.
실제 Torch 런타임은 CUDA 12.8 빌드이지만 게이트의 문자열 조건은 만족하지 않는다.
requirements를 새 격리 환경에 설치할 때 선택된 배포판의 메타데이터 차이를
1단계 준비에서 확인하지 못했다.

고정 check_env.py --sections packages와 gate_env_check.py로 재현했으며 게이트 종료 코드는 1이다.
게이트 완화, config 변경, Torch 재설치 또는 다른 환경으로 전환하지 않았다.
이후 진행 중이던 smoke 드라이버와 자식 프로세스만 종료했다. 파드는 Stop/Terminate하지 않았다.
중단 후 고정 코드 검증을 다시 통과했고 파드 Git 작업 트리도 깨끗했다.

## 생성 결과

| 항목 | E1 | E2 |
|---|---|---|
| 900문항 생성 | 미실행 | 미실행 |
| 생성 시간 | 해당 없음 | 해당 없음 |
| length 종료 수 | 해당 없음 | 해당 없음 |
| 입력·출력 토큰 합계·평균 | 해당 없음 | 해당 없음 |
| 생성 최대 VRAM | 해당 없음 | 해당 없음 |
| 병합 모델·해시 | 병합 미완료, 없음 | 미실행, 없음 |
| raw SHA-256 | raw 없음 | raw 없음 |

3문항 시험 생성도 시작하지 않았다. 전체 환경 게이트·900문항 preflight는 미실행이다.
900 ID·30×30 raw 검증과 E1/E2 raw 전송은 수행할 결과가 없다.
E1/E2 본 실행 폴더는 생성하지 않았다. 중단 후 GPU는 1 MiB, 사용률 0%였다.
이 값은 유휴 상태 확인이며 생성 최대 VRAM 측정값이 아니다.

## 기록 보관

- 파드: /workspace/hypB_eval_20261101/records/, smoke_E1/merge.log.
- 로컬: work/eval_B_20261101/runs/setup_20261101/.
  setup.log, 패키지 게이트 원문, 버전 진단, GPU·패키지 목록, 실제 실행 스크립트를 보관했다.
- 기록 압축 파일 setup_records_20261101.tar.gz의 SHA-256은 파드·로컬 모두
  9a8dd49020755df6197dfe1d392cfc0d8befb4a2fd7589c0bcb5446c380be594로 일치했다.
- Git에는 gpu_20261101_setup/의 요약·전송 검증·패키지/GPU 목록·실행 스크립트만 포함한다.
  모델 가중치, HF 캐시·토큰, raw, 문항별 채점 결과는 포함하지 않는다.
- E1/E2의 요청 경로 runs/E1/, runs/E2/에는 생성 결과가 없다.

## 현재 판단

평가 2단계는 완료되지 않았다. 재개 전에 Torch 배포 메타데이터와 고정 게이트 조건의
불일치를 해결해야 하며 이번 작업에서는 변경하지 않고 멈췄다.
실행 중인 생성 작업은 없고 필요한 실패 기록은 로컬에 백업됐다.
기록 보존 측면에서는 파드를 종료해도 되지만, 재개 시 설치 환경과 모델 캐시를 재사용하려면
현재 /workspace를 보존해야 한다. 파드 종료는 사용자가 직접 판단·수행한다.

## 변경 기록: baseline 설치 방식으로 재개

2026-11-01 사용자 지시에 따라 설치·생성 환경만 baseline 절차로 복구한다.
기본 python3.12의 배포 메타데이터와 torch.__version__ 모두 2.8.0+cu128임을 먼저 확인했다.
기본 python 명령도 같은 /usr/bin/python3.12를 가리키며 기본 환경에는 PEFT가 없다.

- setup_gpu.sh의 venv 생성과 PEFT 설치를 제거했다. 이미지 기본 Python에서 main과 같은
  python -m pip install -r code/requirements.txt 명령을 사용하고, 설치 전후 Torch 두 버전이
  2.8.0+cu128인지 확인한다. 기본 Python에는 PEFT를 설치하지 않는다.
- run_gpu.sh는 기존 /workspace/hypB-eval-env를 병합에만 사용한다.
  check_env·preflight·생성·검증은 기본 Python으로 실행하며 main run_generate.sh의 --install도 그대로 사용한다.
- smoke/E1/E2를 각각 선택할 수 있게 하고 실행별 새 폴더만 허용한다. 병합 safetensors의 SHA-256을 기록한다.
- check_env.py·gate·config.yaml·requirements.txt는 수정하지 않는다.
  Torch 재설치·인덱스 변경·게이트 우회도 하지 않는다. 불일치나 실행 실패 시 중단한다.
- 재개 결과는 별도 새 실행 폴더에서 기록한다. 위 최초 실패 기록은 그대로 보존한다.
- 기본 Python의 최초 설치 명령이 PEP 668 제한을 반환했다. main 설치 블록에 이미 있는
  externally-managed-environment 감지 및 --break-system-packages 재시도 처리를 setup_gpu.sh에도
  그대로 반영했다. 이 처리를 처음 옮길 때 누락했으며, 게이트·config·requirements는 변경하지 않았다.
