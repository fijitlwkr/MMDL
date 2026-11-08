#!/usr/bin/env python3
"""가설 A RL 사전 테스트 A: 원본 모델로 bench64 64문항 × 8회 생성해 속도·길이·정답 분포를 잰다. 학습 없음.

  python experiments/hypA-rl-bench/test_a_generate.py --bench <bench64 폴더> --model_dir <모델 폴더> --out <출력 폴더>

평가 코드를 그대로 쓴다: code/config.yaml, vllm_engine.py 의 VLLMEngine(llm_kwargs)·sampling_kwargs, inputs.py 의 prepare_inputs.
  - 메시지: user 1개 = [이미지, bench64 의 prompt 그대로]. 이미지에는 config 의 min/max_pixels 를 붙인다.
  - 생성 설정: config 값(temp 0.7, top_p 0.8, top_k 20, presence_penalty 1.5, max_tokens 8192) 그대로.
    seed 만 요청마다 다르게 준다(config seed + 요청 번호). 같은 문항의 8개 응답이 서로 다른지는 ⑤에서 확인한다.
  - 소스(OMR / Honey)별로 따로 한 번에 넣어서 소스별 시간을 잰다. 한 소스 = 32문항 × 8 = 256 요청.
정답은 judge 없이 규칙으로 단순 비교한다(팀 파서 code/scoring/frozen/parsers.py 재사용).
  - 객관식: 팀 규칙(Qwen 파서 + Final Answer, 둘이 다르면 미추출) → 실패하면 보조 규칙(FALLBACKS).
  - 주관식: MMMU 주관식 규칙(eval_open).
  - 답을 못 뽑은 응답은 오답으로 센다(개수는 따로 적는다).
출력: responses.jsonl(응답 1개당 1줄), summary.json, REPORT.md
"""
import argparse, collections, hashlib, importlib.metadata, importlib.util, json, os, re, statistics as st, sys, time
from pathlib import Path

# ms-swift 가 설치돼 있으면 vLLM 이 swift 의 플러그인(swift_uembed)을 자동으로 불러오는데, vllm 0.11.0 에 없는 모듈을 찾다가
# LLM 생성이 실패한다. 평가 코드는 플러그인을 쓰지 않으므로 끈다(빈 목록 = 외부 플러그인 없음).
os.environ.setdefault("VLLM_PLUGINS", "")

REPO = Path(__file__).resolve().parents[2]
THRESHOLDS = (1024, 2048, 4096, 8192)
OPTION = re.compile(r"^([A-I])\. (.*)$")
# 팀 규칙이 못 뽑았거나 팀 규칙끼리 답이 다를 때 쓰는 보조 규칙. E0 seed 42 객관식 847문항에서 정오 판정이 팀 공식
# 채점(judge 포함)과 814문항(96.1%) 같았다. 끝까지 쓴 답(734문항)만 보면 732문항(99.7%). 나머지는 8192 토큰에서
# 잘린 답이다(judge 는 잘린 답에서도 답을 읽어 정답 처리한다).
FALLBACKS = (
    ("stated", re.compile(r"(?:final answer|correct answer is|correct option is|correct choice is|answer is|answer)"
                          r"\s*[:：]?\s*\**\s*(?:option\s*)?\(?\**([A-I])\b", re.I), 600),
    ("boxed", re.compile(r"\\boxed\{\s*(?:\\text\{)?\s*\(?([A-I])\b"), 600),
    ("bold", re.compile(r"\*\*\s*\(?([A-I])(?:[.):]|\*\*)"), 300),
)


def choices_of(row):
    lines = row["prompt"].split("\n")
    opts = {}
    for line in lines[lines.index("Options:") + 1:]:
        m = OPTION.match(line)
        if m:
            opts[m.group(1)] = m.group(2)
    if len(opts) != row["n_options"]:
        raise ValueError(f"{row['id']}: {len(opts)} options parsed, n_options={row['n_options']}")
    return opts


def load_parsers(code_dir):
    spec = importlib.util.spec_from_file_location("frozen_parsers", code_dir / "scoring" / "frozen" / "parsers.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def extract_mc(P, text, choices):
    """객관식 답 글자와 뽑은 규칙. 팀 규칙(Qwen 파서 + Final Answer)이 못 뽑거나 둘이 다르면
    답 끝부분에서 마지막으로 밝힌 답 → \\boxed{X} → **X. 순으로 찾는다."""
    qwen = P.qwen_parse(text, choices)
    final = P.marker(text, choices)["answer"]
    conflict = bool(qwen and final and qwen != final)
    if not conflict and (qwen or final):
        return qwen or final, "team"
    prefix = "conflict_" if conflict else ""
    for route, rx, tail in FALLBACKS:
        hits = [m.group(1).upper() for m in rx.finditer(text[-tail:]) if m.group(1).upper() in choices]
        if hits:
            return hits[-1], prefix + route
    return None, prefix + "none"


def grade(P, row, text):
    """(뽑은 답, 정답 여부, 규칙). 답을 못 뽑으면 (None 또는 [], False, ...)."""
    if row["type"] == "mc":
        pred, route = extract_mc(P, text, row["choices"])
        return pred, pred == row["gold"], route
    cands = P.open_candidates(text)
    return cands, bool(cands) and bool(P.MMMU["eval_open"](row["gold"], cands)), "mmmu_open"


def summarize(recs, n, max_tokens, seconds=None):
    toks = [r["output_tokens"] for r in recs]
    by_item = collections.defaultdict(list)
    for r in recs:
        by_item[r["id"]].append(r)
    over = {}
    for t in THRESHOLDS:
        if t < max_tokens:
            over[f">{t}"] = sum(x > t for x in toks) / len(toks)
        else:  # 상한 이상은 길이로 셀 수 없으므로 잘린 비율(finish_reason=length)로 센다
            over[f"{t} 도달(잘림)"] = sum(r["finish_reason"] == "length" for r in recs) / len(recs)
    correct = collections.Counter(sum(r["correct"] for r in g) for g in by_item.values())
    distinct = collections.Counter(len({r["raw_text"] for r in g}) for g in by_item.values())
    out = {"items": len(by_item), "responses": len(recs), "output_tokens_sum": sum(toks),
           "output_tokens_mean": st.mean(toks), "output_tokens_median": st.median(toks), "output_tokens_max": max(toks),
           "over_threshold_share": over, "accuracy": sum(r["correct"] for r in recs) / len(recs),
           "unparsed": sum(r["pred"] in (None, []) for r in recs),
           "parse_routes": dict(collections.Counter(r.get("parse_route") for r in recs)),
           "correct_count_dist": {k: correct.get(k, 0) for k in range(n + 1)},
           "items_mixed": sum(v for k, v in correct.items() if 0 < k < n),
           "distinct_responses_dist": {k: distinct.get(k, 0) for k in range(1, n + 1)}}
    if seconds is not None:
        out.update({"seconds": seconds, "output_tokens_per_second": sum(toks) / seconds})
    return out


def report(summary):
    S, n = summary["groups"], summary["n"]
    L = ["# 테스트 A: 생성 속도·길이·정답 분포", "",
         f"원본 모델 `{summary['model']['repo_id']}`@{summary['model']['revision'][:7]}, bench64 64문항 × {n}회. "
         f"GPU {summary['env'].get('gpu')}. 생성 설정은 `code/config.yaml` 그대로, seed 만 요청마다 다름.", "",
         "## 소스별 결과", "",
         "| 소스 | 문항 | 응답 | ① 시간(분) | ② 생성 토큰 합 | 토큰/초 | 평균 / 중앙 / 최대 토큰 | 정답률 | 답 미추출 |",
         "|---|---|---|---|---|---|---|---|---|"]
    for name, g in S.items():
        sec = f"{g['seconds'] / 60:.1f}" if "seconds" in g else "-"
        tps = f"{g['output_tokens_per_second']:.0f}" if "seconds" in g else "-"
        L.append(f"| {name} | {g['items']} | {g['responses']} | {sec} | {g['output_tokens_sum']:,} | {tps} | "
                 f"{g['output_tokens_mean']:.0f} / {g['output_tokens_median']:.0f} / {g['output_tokens_max']} | "
                 f"{g['accuracy'] * 100:.1f}% | {g['unparsed']} |")
    keys = list(next(iter(S.values()))["over_threshold_share"])
    L += ["", "## ③ 길이 임계값 초과 비율", "", "| 소스 | " + " | ".join(keys) + " |", "|---" * (len(keys) + 1) + "|"]
    for name, g in S.items():
        L.append(f"| {name} | " + " | ".join(f"{g['over_threshold_share'][k] * 100:.1f}%" for k in keys) + " |")
    L += ["", f"`>t` = 생성 토큰이 t 초과. 마지막 열은 상한({summary['max_tokens']})까지 써서 잘린 비율.", "",
          f"## ④ 문항별 정답 횟수 (0~{n}회) 분포 — 문항 수", "",
          "| 소스 | " + " | ".join(map(str, range(n + 1))) + " | 섞인 문항(1~" + str(n - 1) + "회) |",
          "|---" * (n + 3) + "|"]
    for name, g in S.items():
        d = g["correct_count_dist"]
        L.append(f"| {name} | " + " | ".join(str(d[k]) for k in range(n + 1)) + f" | {g['items_mixed']} |")
    L += ["", f"0회·{n}회 문항은 {n}개 응답의 보상이 모두 같아 GRPO 학습 신호가 없다.", "",
          f"## ⑤ 문항별 서로 다른 응답 수 (1~{n}) 분포 — 문항 수", "",
          "| 소스 | " + " | ".join(map(str, range(1, n + 1))) + " |", "|---" * (n + 1) + "|"]
    for name, g in S.items():
        d = g["distinct_responses_dist"]
        L.append(f"| {name} | " + " | ".join(str(d[k]) for k in range(1, n + 1)) + " |")
    L += ["", "응답 원문이 글자까지 같으면 같은 응답으로 셌다.", "",
          "## 정답 판정 방법", "",
          "judge 없이 규칙만 썼다. 객관식은 팀 규칙(Qwen 파서 + Final Answer, 서로 다르면 미추출)을 먼저 쓰고, "
          "못 뽑거나 둘이 다르면 답 끝부분에서 마지막으로 밝힌 답(`answer is X` 등) → `\\boxed{X}` → `**X.` 순으로 찾았다. "
          "이 방식은 E0 seed 42 객관식 847문항에서 정오 판정이 팀 공식 채점(judge 포함)과 96.1% 같았다(끝까지 쓴 답만 보면 99.7%, 나머지는 잘린 답). "
          "주관식은 MMMU 주관식 규칙(`eval_open`). 미추출은 오답으로 셌다.", "",
          "| 그룹 | 답을 뽑은 규칙별 응답 수 |", "|---|---|"]
    for name, g in S.items():
        L.append(f"| {name} | " + ", ".join(f"{k} {v}" for k, v in sorted(g["parse_routes"].items(), key=lambda kv: -kv[1])) + " |")
    L += ["",
          f"모델 로드 {summary['timing']['engine_init_seconds']:.0f}초, 입력 전처리 {summary['timing']['prepare_seconds']:.0f}초는 ① 시간에 넣지 않았다."]
    return "\n".join(L) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bench", type=Path, required=True, help="bench64.jsonl 과 images/ 가 있는 폴더")
    ap.add_argument("--model_dir", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--config", type=Path, default=REPO / "code" / "config.yaml")
    ap.add_argument("--n", type=int, default=8, help="문항당 생성 횟수")
    ap.add_argument("--limit", type=int, default=0, help="소스당 문항 수 제한(동작 확인용, 0 = 전부)")
    a = ap.parse_args()

    import yaml
    from PIL import Image
    code_dir = a.config.resolve().parent
    sys.path.insert(0, str(code_dir))
    from inputs import load_processor, prepare_inputs
    from vllm_engine import VLLMEngine, sampling_kwargs

    config_bytes = a.config.read_bytes()
    cfg = yaml.safe_load(config_bytes)
    P = load_parsers(code_dir)
    rows = [json.loads(line) for line in open(a.bench / "bench64.jsonl", encoding="utf-8")]
    sources = sorted({r["source"] for r in rows})
    if a.limit:
        rows = [r for s in sources for r in [x for x in rows if x["source"] == s][:a.limit]]
    for r in rows:
        if r["type"] == "mc":
            r["choices"] = choices_of(r)
    a.out.mkdir(parents=True, exist_ok=True)

    t0 = time.monotonic()
    processor = load_processor(a.model_dir, cfg)
    prepared = {}
    for r in rows:
        image = Image.open(a.bench / r["image_path"])
        image.load()
        messages = [{"role": "user", "content": [
            {"type": "image", "image": image, "min_pixels": cfg["image"]["min_pixels"], "max_pixels": cfg["image"]["max_pixels"]},
            {"type": "text", "text": r["prompt"]}]}]
        prepared[r["id"]], sizes = prepare_inputs(messages, processor)
        r["image_size"] = list(sizes[0])
    prepare_seconds = time.monotonic() - t0

    engine = VLLMEngine(cfg, a.model_dir)
    from vllm import SamplingParams
    base = sampling_kwargs(cfg)
    max_tokens = base["max_tokens"]
    print("sampling", base, flush=True)

    recs, groups, g = [], {}, 0
    with open(a.out / "responses.jsonl", "w", encoding="utf-8") as f:
        for source in sources:
            sub = [r for r in rows if r["source"] == source]
            reqs = [(r, k, base["seed"] + g + i) for i, (r, k) in enumerate((r, k) for r in sub for k in range(a.n))]
            g += len(reqs)
            print(f"=== {source}: {len(sub)} items x {a.n} = {len(reqs)} requests", flush=True)
            started = time.monotonic()
            outs = engine.llm.generate([dict(prepared[r["id"]]) for r, _, _ in reqs],
                                       [SamplingParams(**{**base, "seed": seed}) for _, _, seed in reqs], use_tqdm=True)
            seconds = time.monotonic() - started
            src_recs = []
            for (r, k, seed), out in zip(reqs, outs):
                c = out.outputs[0]
                pred, ok, route = grade(P, r, c.text)
                rec = {"id": r["id"], "source": source, "subset": r["subset"], "type": r["type"], "gold": r["gold"],
                       "rep": k, "seed": seed, "image_size": r["image_size"], "prompt_tokens": len(out.prompt_token_ids),
                       "output_tokens": len(c.token_ids), "finish_reason": c.finish_reason, "pred": pred, "correct": ok,
                       "parse_route": route, "raw_text": c.text}
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                src_recs.append(rec)
            groups[source] = summarize(src_recs, a.n, max_tokens, seconds)
            print(f"=== {source}: {seconds / 60:.1f} min, {groups[source]['output_tokens_sum']:,} tokens", flush=True)
            recs += src_recs
    for (source, qtype) in sorted({(r["source"], r["type"]) for r in recs}):
        part = [r for r in recs if r["source"] == source and r["type"] == qtype]
        if len(part) < sum(r["source"] == source for r in recs):
            groups[f"{source} / {qtype}"] = summarize(part, a.n, max_tokens)
    groups["전체"] = summarize(recs, a.n, max_tokens, sum(groups[s]["seconds"] for s in sources))

    versions = {}
    for dist in ["torch", "vllm", "transformers", "tokenizers", "qwen-vl-utils", "datasets", "ms-swift"]:
        try:
            versions[dist] = importlib.metadata.version(dist)
        except Exception:
            versions[dist] = None
    try:
        import torch
        versions["gpu"] = torch.cuda.get_device_name(0)
    except Exception:
        pass
    summary = {"n": a.n, "max_tokens": max_tokens, "sampling": base, "seed_rule": "config seed + request index",
               "config_sha256": hashlib.sha256(config_bytes).hexdigest(), "model": cfg["model"],
               "vllm_plugins_env": os.environ.get("VLLM_PLUGINS"),
               "bench_sha256": hashlib.sha256((a.bench / "bench64.jsonl").read_bytes()).hexdigest(),
               "env": versions, "engine": engine.describe(), "memory": engine.memory_report(),
               "timing": {"prepare_seconds": prepare_seconds, "engine_init_seconds": engine.init_seconds},
               "groups": groups}
    (a.out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1, default=str) + "\n", encoding="utf-8")
    (a.out / "REPORT.md").write_text(report(summary), encoding="utf-8")
    print(report(summary))


if __name__ == "__main__":
    main()
