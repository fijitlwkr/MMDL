"""Reuse cached files and download missing data sequentially with rate-limit waits."""
import hashlib
import json
import time
from pathlib import Path

from huggingface_hub import HfApi, hf_hub_download, try_to_load_from_cache
from huggingface_hub.utils import HfHubHTTPError

REPO = "MMDL-team4/hypB-train-data"
COMMIT = "1833bac3be047aa8bd146492436323bb7c14092a"
HASHES = {
    "E1_train_swift.jsonl": "a8405759de84c93904dab137c16106b657e5b05682a0fd755b955c2f707941ab",
    "E2_train_swift.jsonl": "f4f20537d5a77133c7f86c998bb270a383e6db52b1f134a17d786addcbcecf39",
    "holdout_300_swift.jsonl": "8a68baafb77c0da00b656fe0def4dff34e1baffabd75b919eaf4510ac902d70e",
}
OUT = Path(__file__).resolve().parent / "artifacts/pilot_resume_20261101"


def main():
    info = HfApi().dataset_info(REPO, revision="v1.1")
    assert info.sha == COMMIT
    cached = downloaded = waits = 0
    started = time.monotonic()
    print("data commit", info.sha, "files", len(info.siblings), flush=True)
    for index, file in enumerate(info.siblings, 1):
        path = try_to_load_from_cache(REPO, file.rfilename, repo_type="dataset", revision=COMMIT)
        if isinstance(path, str) and Path(path).is_file():
            cached += 1
        else:
            for attempt in range(4):
                try:
                    path = hf_hub_download(REPO, file.rfilename, repo_type="dataset",
                                           revision=COMMIT, force_download=False)
                    downloaded += 1
                    time.sleep(0.5)
                    break
                except (HfHubHTTPError, RuntimeError) as error:
                    response = getattr(error, "response", None)
                    rate_limited = (getattr(response, "status_code", None) == 429
                                    or any(word in str(error).lower()
                                           for word in ("429", "rate limit", "quota of")))
                    if not rate_limited or attempt == 3:
                        raise RuntimeError(f"download failed at {file.rfilename}: {type(error).__name__}") from None
                    waits += 1
                    print("rate limit, waiting 310 seconds", flush=True)
                    time.sleep(310)
        if index % 25 == 0 or index == len(info.siblings):
            print("files", index, "/", len(info.siblings), "cached", cached,
                  "downloaded", downloaded, "waits", waits, flush=True)
    roots = []
    for name, expected in HASHES.items():
        path = Path(try_to_load_from_cache(REPO, name, repo_type="dataset", revision=COMMIT))
        assert hashlib.sha256(path.read_bytes()).hexdigest() == expected, name
        roots.append(path.parent)
    assert len(set(roots)) == 1
    OUT.mkdir(parents=True, exist_ok=True)
    result = dict(data=str(roots[0]), commit=COMMIT, cached=cached, downloaded=downloaded,
                  rate_limit_waits=waits, seconds=time.monotonic() - started, sha256=HASHES)
    (OUT / "download_info.json").write_text(json.dumps(result, indent=2))
    print("download complete", json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
