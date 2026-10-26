"""이미지 pHash 계산과 비교. 팀 공용(Honey, OpenMedReason 모두 이 함수로 비교한다).

pHash = imagehash.phash(img, hash_size=8) → 64비트 16진수 문자열.
해밍 거리 = 두 지문에서 다른 비트 수. 0에 가까울수록 같은 이미지.
"""
import csv
import io
from typing import Dict, Iterable, List, Tuple

from PIL import Image

try:
    import imagehash
except ImportError:  # imagehash 가 없으면 같은 계산(numpy+scipy)으로 대신한다. 300장 비교에서 전부 일치
    imagehash = None

HASH_SIZE = 8  # 64 bit


def _phash(img: Image.Image) -> str:
    if imagehash is not None:
        return str(imagehash.phash(img, hash_size=HASH_SIZE))
    import numpy as np
    import scipy.fftpack
    n = HASH_SIZE * 4
    px = np.asarray(img.convert("L").resize((n, n), Image.Resampling.LANCZOS))
    dct = scipy.fftpack.dct(scipy.fftpack.dct(px, axis=0), axis=1)
    low = dct[:HASH_SIZE, :HASH_SIZE]
    bits = "".join("1" if b else "0" for b in (low > np.median(low)).flatten())
    return format(int(bits, 2), f"0{HASH_SIZE * HASH_SIZE // 4}x")


def phash_from_bytes(b: bytes) -> str:
    return _phash(Image.open(io.BytesIO(b)).convert("RGB"))


def phash_from_pil(img: Image.Image) -> str:
    return _phash(img.convert("RGB"))


def hamming(h1: str, h2: str) -> int:
    return bin(int(h1, 16) ^ int(h2, 16)).count("1")


def load_index(csv_path: str) -> List[Tuple[str, str]]:
    """mmmu_phash.csv → [(ref_id, phash), ...]. ref_id = '{split}/{id}#{image_idx}'."""
    rows = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            rows.append((f"{r['split']}/{r['id']}#{r['image_idx']}", r["phash"]))
    return rows


def nearest(h: str, index: List[Tuple[str, str]]) -> Tuple[str, int]:
    """index에서 가장 가까운 항목과 해밍 거리."""
    best_id, best_d = "", 65
    for ref_id, ref_h in index:
        d = hamming(h, ref_h)
        if d < best_d:
            best_id, best_d = ref_id, d
            if d == 0:
                break
    return best_id, best_d


def classify(d: int, exclude_le: int = 8, review_le: int = 12) -> str:
    """거리 ≤8 → exclude(제외), 9~12 → review(눈으로 확인), 그 외 keep."""
    if d <= exclude_le:
        return "exclude"
    if d <= review_le:
        return "review"
    return "keep"
