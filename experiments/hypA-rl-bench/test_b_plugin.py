#!/usr/bin/env python3
"""가설 A RL 사전 테스트 B: ms-swift 플러그인 + 보조 명령.

swift rlhf --external_plugins 로 불러오면(import) 세 가지가 붙는다. 기록은 환경변수 HYPA_B_OUT 폴더에 쓴다.
  1. 보상 answer_in_response (임시 보상): 응답에 정답이 있으면 1, 없으면 0.
     객관식은 정답 글자가 단독 대문자(앞뒤가 영문자가 아님)로 한 번이라도 나오면 1. 주관식은 정답 문자열
     (끝 마침표 제거, 대소문자 무시)이 응답에 들어 있으면 1. 호출마다 rewards.jsonl 에 남긴다.
  2. 프롬프트 덤프: vLLM 에 들어가는 첫 요청의 토큰 id·이미지 크기·샘플링 설정을 prompt_dump.json 에 남긴다.
  3. overlong 로그: 손실 계산 직전 배치마다 잘린 응답 수와 그 응답들의 토큰 수를 overlong.jsonl 에 남긴다.
     overlong_filter 가 켜져 있으면 swift 가 이 토큰들을 손실 마스크에서 뺀다
     (swift/rlhf_trainers/grpo_trainer.py 의 _compute_loss_and_metrics, 4.6.0 기준 965~970행).

직접 실행하면 보조 명령이다.
  python test_b_plugin.py prepare   --bench <bench64> --out <jsonl> [--n 16]
  python test_b_plugin.py compare   --dump <prompt_dump.json> --bench <bench64> --model_dir <모델> --out <json>
  python test_b_plugin.py summarize --b_out <HYPA_B_OUT> --out <폴더>
"""
import argparse, collections, importlib.util, json, os, random, re, sys, time, traceback
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
OUT = Path(os.environ["HYPA_B_OUT"]) if os.environ.get("HYPA_B_OUT") else None


def _append(name, rec):
    if OUT is not None:
        rec = {"time": time.time(), **rec}
        with open(OUT / name, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")


def _norm(text):
    return text.strip().rstrip(".").strip().lower()


def answer_in_response(completion, gold, qtype):
    if qtype == "mc":
        return float(re.search(rf"(?<![A-Za-z]){re.escape(gold[0])}(?![A-Za-z])", completion) is not None)
    return float(any(_norm(g) and _norm(g) in completion.lower() for g in gold))


# ---------------------------------------------------------------- swift 플러그인 (import 될 때만)
def _patch_failed(what):
    if OUT is not None:
        with open(OUT / "plugin_errors.txt", "a", encoding="utf-8") as f:
            f.write(f"== {what}\n{traceback.format_exc()}\n")


def _register_reward():
    from swift.rewards import ORM, orms

    class AnswerInResponse(ORM):
        def __call__(self, completions, gold, qtype, item_id=None, is_truncated=None, trainer_state=None, **kwargs):
            rewards = [answer_in_response(c, g, t) for c, g, t in zip(completions, gold, qtype)]
            step = getattr(trainer_state, "global_step", None)
            truncated = is_truncated or [None] * len(rewards)
            ids = item_id or [None] * len(rewards)
            for i, (r, c) in enumerate(zip(rewards, completions)):
                _append("rewards.jsonl", {"step": step, "item_id": ids[i], "qtype": qtype[i], "gold": gold[i],
                                          "is_truncated": truncated[i], "chars": len(c), "reward": r})
            return rewards

    orms["answer_in_response"] = AnswerInResponse


def _patch_prompt_dump():
    from swift.infer_engine.vllm_engine import VllmEngine
    original = VllmEngine._add_request
    state = {"dumped": False}

    def _add_request(self, inputs, generation_config, *args, **kwargs):
        if not state["dumped"] and OUT is not None:
            state["dumped"] = True
            try:
                images = inputs.get("images") or []
                dump = {"input_ids": [int(x) for x in inputs["input_ids"]],
                        "image_sizes": [list(getattr(im, "size", ())) for im in images],
                        "mm_processor_kwargs": inputs.get("mm_processor_kwargs"),
                        "sampling_params": repr(generation_config)}
                (OUT / "prompt_dump.json").write_text(json.dumps(dump, ensure_ascii=False, default=str), encoding="utf-8")
            except Exception:
                _patch_failed("prompt dump")
        return original(self, inputs, generation_config, *args, **kwargs)

    VllmEngine._add_request = _add_request


def _patch_overlong_log():
    from swift.rlhf_trainers.grpo_trainer import GRPOTrainer
    original = GRPOTrainer._compute_loss_and_metrics

    def _compute_loss_and_metrics(self, model, model_inputs, grpo_batch):
        try:
            trunc = grpo_batch.truncated_mask.bool()
            mask = grpo_batch.completion_mask.bool()
            _append("overlong.jsonl", {"step": self.state.global_step, "overlong_filter": bool(self.overlong_filter),
                                       "samples": int(trunc.numel()), "truncated": int(trunc.sum()),
                                       "completion_tokens": int(mask.sum()), "truncated_tokens": int(mask[trunc].sum())})
        except Exception:
            _patch_failed("overlong log")
        return original(self, model, model_inputs, grpo_batch)

    GRPOTrainer._compute_loss_and_metrics = _compute_loss_and_metrics


if __name__ != "__main__" and importlib.util.find_spec("swift") is not None:
    _register_reward()  # 보상이 없으면 학습이 돌 수 없으므로 실패하면 그대로 에러를 낸다
    for _name, _patch in (("prompt dump patch", _patch_prompt_dump), ("overlong log patch", _patch_overlong_log)):
        try:
            _patch()
        except Exception:
            _patch_failed(_name)


# ---------------------------------------------------------------- 보조 명령
def cmd_prepare(a):
    """16문항 고정 선택: OMR 8 + Honey 8(TQA 객관식 4, ChartQA 2, TallyQA 2). 같은 seed 면 항상 같은 16문항."""
    rows = sorted((json.loads(line) for line in open(a.bench / "bench64.jsonl", encoding="utf-8")), key=lambda r: r["id"])
    quota = {("neginb/OpenMedReason", None): a.n // 2, ("HoneyDataV2/Honey-Data-V2", "TQA"): a.n // 4,
             ("HoneyDataV2/Honey-Data-V2", "ChartQA"): a.n // 8, ("HoneyDataV2/Honey-Data-V2", "TallyQA"): a.n // 8}
    rng = random.Random(a.seed)
    picked = []
    for (source, subset), k in quota.items():
        pool = [r for r in rows if r["source"] == source and (subset is None or r["subset"] == subset)]
        picked += rng.sample(pool, k)
    assert len(picked) == a.n, f"quota sums to {len(picked)}, not {a.n}"
    a.out.parent.mkdir(parents=True, exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        for r in picked:
            gold = r["gold"] if isinstance(r["gold"], list) else [r["gold"]]
            f.write(json.dumps({"messages": [{"role": "user", "content": "<image>" + r["prompt"]}],
                                "images": [str((a.bench / r["image_path"]).resolve())],
                                "gold": gold, "qtype": r["type"], "item_id": r["id"], "bench_source": r["source"]},
                               ensure_ascii=False) + "\n")
    print(f"{len(picked)} items -> {a.out}:", collections.Counter((r["source"], r["subset"]) for r in picked))


def cmd_compare(a):
    """첫 롤아웃 프롬프트(swift → vLLM)를 평가 코드(code/inputs.py prepare_inputs)가 만드는 입력과 비교한다."""
    import yaml
    from PIL import Image
    code_dir = a.config.resolve().parent
    sys.path.insert(0, str(code_dir))
    from inputs import load_processor, prepare_inputs
    cfg = yaml.safe_load(a.config.read_text())
    dump = json.loads(a.dump.read_text())
    processor = load_processor(a.model_dir, cfg)
    tok = processor.tokenizer
    swift_ids = dump["input_ids"]
    swift_text = tok.decode(swift_ids, skip_special_tokens=False)
    rows = [json.loads(line) for line in open(a.bench / "bench64.jsonl", encoding="utf-8")]
    hits = [r for r in rows if r["prompt"] in swift_text]
    if len(hits) != 1:
        raise SystemExit(f"덤프와 맞는 bench64 문항이 {len(hits)}개라 비교할 수 없음")
    row = hits[0]
    image = Image.open(a.bench / row["image_path"])
    image.load()
    messages = [{"role": "user", "content": [
        {"type": "image", "image": image, "min_pixels": cfg["image"]["min_pixels"], "max_pixels": cfg["image"]["max_pixels"]},
        {"type": "text", "text": row["prompt"]}]}]
    prepared, sizes = prepare_inputs(messages, processor)
    team_text = prepared["prompt"]
    team_ids = tok(team_text, add_special_tokens=False)["input_ids"]
    team_full = processor(text=[team_text], images=prepared["multi_modal_data"]["image"], do_resize=False)["input_ids"][0]
    team_full = team_full.tolist() if hasattr(team_full, "tolist") else list(team_full)  # return_tensors 없으면 list
    if swift_ids == team_ids:
        ids_match = "같음 (이미지 자리 1토큰, vLLM 이 펼침 — 평가 코드와 같은 방식)"
    elif swift_ids == team_full:
        ids_match = "같음 (이미지 토큰을 펼친 형태)"
    else:
        ref = team_full if abs(len(swift_ids) - len(team_full)) < abs(len(swift_ids) - len(team_ids)) else team_ids
        i = next((k for k, (x, y) in enumerate(zip(swift_ids, ref)) if x != y), min(len(swift_ids), len(ref)))
        ids_match = (f"다름: swift {len(swift_ids)}토큰 / 평가 {len(ref)}토큰, 첫 차이 위치 {i}: "
                     f"swift {tok.decode(swift_ids[max(0, i - 5):i + 5])!r} / 평가 {tok.decode(ref[max(0, i - 5):i + 5])!r}")
    factor = (cfg["image"]["image_patch_size"] * cfg["image"]["spatial_merge_size"]) ** 2

    def user_text(text):  # <|vision_end|> 뒤부터 첫 <|im_end|> 앞까지 = 이미지 뒤 사용자 텍스트
        return text.split("<|vision_end|>", 1)[-1].split("<|im_end|>", 1)[0]

    def facts(text, size):
        return {"system_prompt": "<|im_start|>system" in text,
                "image_before_text": 0 <= text.find("<|vision_start|>") < text.find(row["prompt"][:30]),
                "image_size": list(size), "pixels": size[0] * size[1], "image_tokens": size[0] * size[1] // factor,
                "pixels_in_range": cfg["image"]["min_pixels"] <= size[0] * size[1] <= cfg["image"]["max_pixels"],
                "user_text_trailing_whitespace": user_text(text) != user_text(text).rstrip(),
                "user_text_tail": user_text(text)[-40:]}

    result = {"item_id": row["id"], "token_ids": ids_match, "text_equal": swift_text == team_text,
              "min_max_pixels": [cfg["image"]["min_pixels"], cfg["image"]["max_pixels"]],
              "swift": facts(swift_text, dump["image_sizes"][0]), "eval": facts(team_text, sizes[0]),
              "swift_sampling_params": dump.get("sampling_params"), "swift_prompt_text": swift_text, "eval_prompt_text": team_text}
    a.out.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if not k.endswith("_text")}, ensure_ascii=False, indent=1))


def _seconds(value):
    """swift 의 elapsed_time('1h 2m 3s' 등) → 초."""
    if isinstance(value, (int, float)):
        return float(value)
    units = {"h": 3600, "m": 60, "s": 1}
    found = re.findall(r"([\d.]+)\s*([hms])", str(value))
    return sum(float(x) * units[u] for x, u in found) if found else None


def _jsonl(path):
    return [json.loads(line) for line in open(path, encoding="utf-8")] if path.is_file() else []


def cmd_summarize(a):
    b = a.b_out
    exit_code = int((b / "exit_code.txt").read_text().strip()) if (b / "exit_code.txt").is_file() else None
    logs = sorted(b.glob("swift/**/logging.jsonl"))
    steps = [r for r in (_jsonl(logs[-1]) if logs else []) if "reward" in r or "loss" in r]
    prev, step_rows = 0.0, []
    for r in steps:
        el = _seconds(r.get("elapsed_time"))
        step_rows.append({"step": r.get("global_step/max_steps", r.get("global_step")), "elapsed_s": el,
                          "step_s": (el - prev) if el is not None else None, "reward": r.get("reward"),
                          "clipped_ratio": r.get("completions/clipped_ratio"), "mean_length": r.get("completions/mean_length"),
                          "loss": r.get("loss"), "kl": r.get("kl"), "memory_gib": r.get("memory(GiB)")})
        prev = el if el is not None else prev
    rewards = _jsonl(b / "rewards.jsonl")
    overlong = _jsonl(b / "overlong.jsonl")
    # 스텝별 생성·학습 시간 나누기: 보상 계산(=생성 직후) 시각과 그 스텝 마지막 손실 계산 시각
    first_reward = {}
    for r in rewards:
        first_reward.setdefault(r["step"], r["time"])
    last_loss = {}
    for r in overlong:
        if "step" in r:
            last_loss[r["step"]] = r["time"]
    split = []
    for s in sorted(first_reward):
        gen = first_reward[s] - last_loss[s - 1] if (s - 1) in last_loss else None
        train = last_loss[s] - first_reward[s] if s in last_loss else None
        split.append({"step_index": s, "generation_s": gen, "training_s": train})
    vram = []
    if (b / "vram.csv").is_file():
        for line in open(b / "vram.csv"):
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 3 and parts[1].isdigit():
                vram.append((int(parts[1]), int(parts[2])))
    ol = collections.Counter()
    for r in overlong:
        if "step" in r:
            ol["samples"] += r["samples"]; ol["truncated"] += r["truncated"]
            ol["completion_tokens"] += r["completion_tokens"]; ol["truncated_tokens"] += r["truncated_tokens"]
    per_step_reward = collections.defaultdict(list)
    for r in rewards:
        per_step_reward[r["step"]].append(r["reward"])
    checkpoints = sorted(b.glob("swift/**/checkpoint-*/adapter_model.safetensors"))
    summary = {"exit_code": exit_code, "success": exit_code == 0, "logged_steps": len(step_rows),
               "saved_checkpoint": str(checkpoints[-1].parent) if checkpoints else None,
               "steps": step_rows, "raw_step_logs": steps, "generation_training_split": split,
               "max_vram_mib": max((v for v, _ in vram), default=None), "gpu_total_mib": vram[0][1] if vram else None,
               "reward_mean_by_step": {k: sum(v) / len(v) for k, v in sorted(per_step_reward.items())},
               "reward_mean_by_qtype": {q: sum(r["reward"] for r in rewards if r["qtype"] == q) /
                                        max(1, sum(r["qtype"] == q for r in rewards)) for q in sorted({r["qtype"] for r in rewards})},
               "overlong": {"overlong_filter": overlong[0].get("overlong_filter") if overlong else None, **ol},
               "prompt_check": json.loads((b / "prompt_check.json").read_text()) if (b / "prompt_check.json").is_file() else None}
    if summary["prompt_check"]:
        for k in ("swift_prompt_text", "eval_prompt_text"):
            summary["prompt_check"].pop(k, None)
    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / "b_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=1))


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("prepare")
    p.add_argument("--bench", type=Path, required=True); p.add_argument("--out", type=Path, required=True)
    p.add_argument("--n", type=int, default=16); p.add_argument("--seed", type=int, default=3407)
    p = sub.add_parser("compare")
    p.add_argument("--dump", type=Path, required=True); p.add_argument("--bench", type=Path, required=True)
    p.add_argument("--model_dir", type=Path, required=True); p.add_argument("--out", type=Path, required=True)
    p.add_argument("--config", type=Path, default=REPO / "code" / "config.yaml")
    p = sub.add_parser("summarize")
    p.add_argument("--b_out", type=Path, required=True); p.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    {"prepare": cmd_prepare, "compare": cmd_compare, "summarize": cmd_summarize}[a.cmd](a)


if __name__ == "__main__":
    main()
