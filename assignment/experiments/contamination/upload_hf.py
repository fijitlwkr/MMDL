"""폴더를 HF 데이터셋 저장소에 올린다. 요청 한도(5분에 1,000번)에 걸리면 5분 넘게 쉬었다가 이어서 올린다.

사용:
  python upload_hf.py --folder upload_omr --repo MMDL-team4/hypA-train-data --path-in-repo incoming/omr \
      --message "Add OMR data (E1/control, 600/1500)"

이미 올라간 파일은 다시 올릴 때 건너뛰므로, 끊겨도 같은 명령을 다시 실행하면 이어진다.
커밋은 모든 파일이 올라간 뒤 한 번만 생긴다. 토큰은 huggingface-cli login 으로 저장된 것을 쓴다(쓰기 권한 필요).
"""
import argparse
import time

from huggingface_hub import HfApi


def rate_limited(e):
    while e is not None:
        if "429" in str(e) or "Too Many Requests" in str(e):
            return True
        e = e.__cause__
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--folder", required=True)
    ap.add_argument("--repo", required=True)
    ap.add_argument("--path-in-repo", required=True)
    ap.add_argument("--message", required=True)
    ap.add_argument("--wait", type=int, default=330, help="한도에 걸렸을 때 쉬는 초")
    ap.add_argument("--tries", type=int, default=8)
    a = ap.parse_args()

    api = HfApi()
    for i in range(1, a.tries + 1):
        try:
            url = api.upload_folder(folder_path=a.folder, path_in_repo=a.path_in_repo, repo_id=a.repo,
                                    repo_type="dataset", commit_message=a.message)
            print("완료:", url)
            return
        except Exception as e:
            if not rate_limited(e) or i == a.tries:
                raise
            print(f"[{i}회차] 요청 한도에 걸림. {a.wait}초 쉬고 이어서 올림 ({time.strftime('%H:%M:%S')})")
            time.sleep(a.wait)


if __name__ == "__main__":
    main()
