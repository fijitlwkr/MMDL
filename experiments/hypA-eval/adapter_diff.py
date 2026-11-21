#!/usr/bin/env python3
"""GRPO LoRA 체크포인트끼리 학습된 변화 ΔW = (alpha/r)·B·A 가 얼마나 다른지 잰다. torch·GPU 없음(numpy).

  python experiments/hypA-eval/adapter_diff.py --adapters <step25/ step50/ ... 가 든 폴더> --steps 25,50,75,100 --out <출력 폴더>

각 step 폴더의 adapter_model.safetensors 와 adapter_config.json 을 읽는다(HF MMDL-team4/hypA-grpo-step100-ckpt 의 폴더 구조).
모듈(252개)마다 저랭크 그대로 내적을 계산해 다음 값의 중앙값·90% 분위를 낸다. 출력: ADAPTER_DIFF.md
  - ‖ΔW_a − ΔW_b‖ / ‖ΔW_b‖ : 두 체크포인트의 상대 차이
  - cos(ΔW_a, ΔW_b)         : 방향 유사도
  - ‖ΔW_a‖ / ‖ΔW_b‖         : 크기 비
"""
import argparse, json, statistics as st, struct
from pathlib import Path

import numpy as np


def load_safetensors(p):
    b = p.read_bytes(); n = struct.unpack("<Q", b[:8])[0]; h = json.loads(b[8:8 + n]); base = 8 + n; out = {}
    for k, v in h.items():
        if k == "__metadata__":
            continue
        s, e = v["data_offsets"]; raw = b[base + s:base + e]
        if v["dtype"] == "F32":
            x = np.frombuffer(raw, np.float32)
        elif v["dtype"] == "BF16":
            x = (np.frombuffer(raw, np.uint16).astype(np.uint32) << 16).view(np.float32)
        else:
            raise SystemExit(f"지원하지 않는 dtype {v['dtype']} ({k})")
        out[k] = x.reshape(v["shape"]).astype(np.float64)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--adapters", type=Path, required=True)
    ap.add_argument("--steps", default="25,50,75,100")
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    steps = [int(s) for s in a.steps.split(",")]
    ad, scale = {}, {}
    for s in steps:
        d = a.adapters / f"step{s}"
        cfg = json.loads((d / "adapter_config.json").read_text())
        scale[s] = cfg["lora_alpha"] / cfg["r"]
        ad[s] = load_safetensors(d / "adapter_model.safetensors")
    keys = sorted(k for k in ad[steps[-1]] if ".lora_A." in k)

    def inner(x, y, k):
        Ax, Bx = ad[x][k], ad[x][k.replace(".lora_A.", ".lora_B.")]
        Ay, By = ad[y][k], ad[y][k.replace(".lora_A.", ".lora_B.")]
        return scale[x] * scale[y] * np.trace((Bx.T @ By) @ (Ay @ Ax.T))

    last = steps[-1]
    pairs = [(s, last) for s in steps[:-1]] + list(zip(steps[:-2], steps[1:-1]))
    L = ["# GRPO 체크포인트 어댑터 비교", "", f"`adapter_diff.py --steps {a.steps}` 가 만든 파일이다. 모듈 {len(keys)}개의 중앙값 (90% 분위).", "",
         "| 비교 | ‖ΔW_a − ΔW_b‖ / ‖ΔW_b‖ | cos(ΔW_a, ΔW_b) | ‖ΔW_a‖ / ‖ΔW_b‖ |", "|---|---|---|---|"]
    for x, y in pairs:
        rel, cos, ratio = [], [], []
        for k in keys:
            xx, yy, xy = inner(x, x, k), inner(y, y, k), inner(x, y, k)
            rel.append(np.sqrt(max(xx + yy - 2 * xy, 0.0)) / np.sqrt(yy))
            cos.append(xy / np.sqrt(xx * yy))
            ratio.append(np.sqrt(xx / yy))
        L.append(f"| step{x} vs step{y} | {st.median(rel):.3f} ({np.percentile(rel, 90):.3f}) | "
                 f"{st.median(cos):.3f} | {st.median(ratio):.3f} |")
    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / "ADAPTER_DIFF.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))


if __name__ == "__main__":
    main()
