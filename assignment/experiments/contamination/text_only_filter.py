"""이미지 없이 질문+보기만 주고 모델에게 여러 번 풀게 해서, 글만으로 풀리는 문항을 찾는다.

사용 (RunPod GPU, vllm 0.11.0):
  python text_only_filter.py --config config.yaml --input filter_input.csv --output filter_result.csv

입력 CSV 열: cand_id, stem, options, answer (그 밖의 열은 그대로 옮김)
출력 CSV: 입력 열 + pred_1..pred_n, raw_1..raw_n, n_correct, drop
  drop = 1 이면 n 번 중 --drop-at 번 이상 맞힘 → 이미지 없이 풀리는 문항으로 보고 뺀다.
모델 revision, 샘플링 값, 엔진 값은 --config(팀 code/config.yaml)에서 읽는다. max_tokens 만 짧게 바꾼다.
"""
import argparse
import csv
import os
import re
import sys
import time

import yaml

PROMPT = "{stem}\n{options}\nAnswer with the option's letter from the given choices directly."
LEAD_RE = re.compile(r"^\s*(?:\(([A-J])\)|([A-J])(?:[\.\):]|\s*$))")
ANSWER_RE = re.compile(r"answer(?: is)?\W{0,12}\(?([A-J])\b", re.I)


def parse_letter(text, valid):
    m = LEAD_RE.match(text) or ANSWER_RE.search(text)
    letter = next((g for g in m.groups() if g), "") if m else ""
    return letter if letter in valid else ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--n", type=int, default=3, help="문항당 풀이 횟수")
    ap.add_argument("--drop-at", type=int, default=2, help="이 횟수 이상 맞히면 drop")
    ap.add_argument("--max-tokens", type=int, default=64)
    a = ap.parse_args()

    cfg = yaml.safe_load(open(a.config, encoding="utf-8"))
    for k, v in cfg["environment"]["env_vars"].items():
        os.environ[k] = v
    from vllm import LLM, SamplingParams

    s, e = cfg["sampling"], cfg["engine"]
    llm = LLM(model=cfg["model"]["repo_id"], revision=cfg["model"]["revision"],
              tokenizer_revision=cfg["model"]["revision"], dtype=cfg["model"]["dtype"],
              seed=s["engine_seed"], max_model_len=cfg["budget"]["max_model_len"],
              gpu_memory_utilization=e["gpu_memory_utilization"], limit_mm_per_prompt=e["limit_mm_per_prompt"],
              trust_remote_code=e["trust_remote_code"], max_num_batched_tokens=e["max_num_batched_tokens"],
              max_num_seqs=e["max_num_seqs"])
    sp = SamplingParams(n=a.n, temperature=s["temperature"], top_p=s["top_p"], top_k=s["top_k"],
                        repetition_penalty=s["repetition_penalty"], presence_penalty=s["presence_penalty"],
                        seed=s["seed"], max_tokens=a.max_tokens, skip_special_tokens=s["skip_special_tokens"])

    rows = list(csv.DictReader(open(a.input, encoding="utf-8")))
    convs = [[{"role": "user", "content": PROMPT.format(stem=r["stem"], options=r["options"])}] for r in rows]
    t0 = time.time()
    outs = llm.chat(convs, sp, use_tqdm=True)
    print(f"{len(rows)} 문항 x {a.n}회, {time.time() - t0:.0f}초")

    fields = list(rows[0].keys()) + [f"pred_{i + 1}" for i in range(a.n)] + [f"raw_{i + 1}" for i in range(a.n)] + ["n_correct", "drop"]
    n_drop = n_noletter = 0
    with open(a.output, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r, o in zip(rows, outs):
            texts = [c.text.strip() for c in o.outputs]
            valid = set(re.findall(r"(?m)^\s*([A-J])[\.\)]", r["options"]))
            preds = [parse_letter(t, valid) for t in texts]
            n_noletter += preds.count("")
            k = sum(p == r["answer"].strip() for p in preds)
            r = dict(r)
            for i in range(a.n):
                r[f"pred_{i + 1}"], r[f"raw_{i + 1}"] = preds[i], texts[i][:200]
            r["n_correct"], r["drop"] = k, int(k >= a.drop_at)
            n_drop += r["drop"]
            w.writerow(r)
    print(f"drop {n_drop} / {len(rows)} ({n_drop / len(rows):.1%}), 글자 못 뽑은 풀이 {n_noletter}회 → {a.output}")


if __name__ == "__main__":
    sys.exit(main())
