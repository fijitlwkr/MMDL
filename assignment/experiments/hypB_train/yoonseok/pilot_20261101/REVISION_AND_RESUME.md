# v1.1 참조 확인과 캐시 재사용

2026-11-01 재확인 결과, 두 해시는 같은 데이터 버전을 나타낸다. 이전 REPORT.md의 커밋 차이는 annotated tag 객체와 실제 커밋을 비교해서 발생한 판정 오류다.

| Git 참조 | 해시 |
|---|---|
| refs/tags/v1.1 (annotated tag 객체) | e9fe258b9d044e0693441a4c54138054d19130ab |
| refs/tags/v1.1^{} (실제 커밋) | 1833bac3be047aa8bd146492436323bb7c14092a |

Git smart HTTP의 참조 광고에서 두 값을 직접 확인했다. HF API에 e9fe258b와 v1.1을 각각 조회하면 모두 실제 커밋 1833bac3로 해석된다. 파일 3,307개의 경로·크기·Git blob ID·LFS SHA-256을 비교한 차이는 0개다. JSONL·이미지·README 변경도 없다. 증거는 git_tag_refs.json과 revision_diff.json에 저장했다.

## 기존 캐시로 이어받는 방법

파드의 huggingface_hub 0.35.3 소스를 확인했다. 전체 커밋 해시로 hf_hub_download를 호출하면 이미 존재하는 snapshot 파일은 네트워크 요청 없이 반환한다. JSONL 세 파일에 대해 HTTP 요청을 예외 처리하도록 막은 상태에서 실제 반환을 확인했다. 기존 캐시는 1,044/3,307개 파일이며 cache_check.json에 기록했다.

동일한 HF_HOME과 실제 커밋 해시, force_download=False로 snapshot_download를 다시 호출하면 기존 캐시를 활용할 수 있다. 아래는 파드의 기존 학습 환경을 사용하는 재개 명령이다.

```bash
cd /workspace/MMDL/assignment/experiments/hypB_train
HF_HOME=/workspace/hf_cache .venv-train/bin/python - <<'PY'
from huggingface_hub import snapshot_download
path = snapshot_download(
    "MMDL-team4/hypB-train-data",
    repo_type="dataset",
    revision="1833bac3be047aa8bd146492436323bb7c14092a",
    force_download=False,
    max_workers=1,
)
print(path)
PY
```

이 명령은 기존 파드 경로를 사용한다. Git 저장소를 새 위치로 맞추거나 환경을 재구성한 경우 해당 Python 경로를 사용해야 한다.

max_workers=1은 동시성만 줄이므로 요청률 상한을 보장하지 않는다. 대량 재개 시에는 실제 커밋의 파일 목록을 한 번 조회한 뒤 캐시에 없는 파일만 hf_hub_download로 순차 처리하고, 요청 사이 지연과 429 응답의 대기를 적용하는 방식이 필요하다. 기본 8개 동시 다운로드에서 반복 호출을 바로 이어가는 방식은 같은 제한을 다시 만날 수 있다. 0.35.3은 최신 문서의 1.2.0 이상 자동 429 대기 기능을 전제로 사용할 수 없다. 학습 환경 패키지 버전 변경 없이 재개 방법을 선택할 수 있다.

HF 공식 캐시 설명과 다운로드 문서는 기존 파일 재사용 및 revision 고정을 설명한다. 요청 제한은 5분 창이며 요청 간격 분산을 안내한다. [캐시 문서](https://huggingface.co/docs/huggingface_hub/guides/manage-cache), [다운로드 문서](https://huggingface.co/docs/huggingface_hub/guides/download), [요청 제한 문서](https://huggingface.co/docs/hub/rate-limits)

현재 소량의 메타데이터 조회는 성공했다. 이번 작업에서는 전체 다운로드 재개와 학습은 실행하지 않았다. 기존 README.md 예제의 snapshot 디렉터리를 e9fe258b로 검사하는 assert는 실제 커밋 해시 1833bac3에 맞춰 재개 전에 교정할 필요가 있다. 사용자 지시에 따라 이전 파일 내용은 경로 수정과 PLAN 교체 외에는 보존했다.
