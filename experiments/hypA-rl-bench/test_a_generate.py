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
  - 주관식: 최종 답 부분(같은 줄의 마지막 'Answer:' 뒤, 없으면 첫 줄 + 마지막 줄)에 정답이 있는지 단순 비교(open_match).
  - 답을 못 뽑은 응답은 오답으로 센다(개수는 따로 적는다).
출력: responses.jsonl(응답 1개당 1줄), summary.json, REPORT.md

  python experiments/hypA-rl-bench/test_a_generate.py --bench <bench64 폴더> --out <출력 폴더> --regrade
    생성 없이 저장된 responses.jsonl 을 지금의 판정 규칙으로 다시 채점한다(GPU 불필요). 시간·토큰 기록은 그대로 둔다.

  python experiments/hypA-rl-bench/test_a_generate.py --input <문항 jsonl> --n 8 --model_dir <모델 폴더> --out <출력 폴더>
    GRPO 문제풀 사전 선별용 생성(2026-11-10 하경님 요청). 입력 형식은 bench64 와 같고 이미지 경로는 jsonl 이 있는 폴더 기준.
    생성 방식은 위 테스트 A 와 같다(config 그대로, 요청마다 seed 다름). --max_tokens 로 생성 상한만 바꿀 수 있다(학습 rollout 상한 2048).
    pred/correct/parse_route 는 테스트 A 와 같은 규칙으로 채운다(객관식 팀 파서가 읽은 결과 확인용). 학습 보상은 데이터 쪽에서 매긴다.
      - seed = config seed + seed_offset + 문항 순번(파일 안 0부터) × n + rep. --limit 로 앞 일부만 돌려도 같은 문항은 같은 seed.
      - 문항을 --chunk_items 개씩 나눠 생성하고 묶음마다 responses.jsonl 에 이어 쓴다. 한 번에 다 넣으면 대기 중인
        요청의 이미지 전처리 결과가 메모리에 쌓인다. 중간에 끊겨도 같은 명령을 다시 실행하면 끝난 문항은 건너뛴다.
      - finish_reason=length(잘림) 응답도 그대로 저장한다.
    출력: responses.jsonl(응답 1개당 1줄: id, rep, seed, finish_reason, output_tokens, pred, correct, parse_route, raw_text …),
          sampling_params.json(실제 적용된 생성 설정), run_info.json(문항 수·seed_offset·시간·토큰·잘림 수)
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
# 주관식(bench64 의 ChartQA·TallyQA): 정답 끝에 마침표가 붙어 있고('Sweden.', '22.07.'), 모델은 '$970 million',
# 'two sinks', 'Answer: Sweden' 처럼 답한다. MMMU 주관식 규칙(eval_open)은 이런 답의 절반가량을 오답 처리해서
# (2026-11-08 응답 128개를 직접 읽어 확인) 최종 답 부분에 정답이 있는지로 단순 비교한다.
ANSWER_LINE = re.compile(r"(?:final answer|answer)[ \t*]*[:：][ \t*]*(\S.*)", re.I)
NUMBER_WORDS = {w: float(i) for i, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen "
    "seventeen eighteen nineteen twenty".split())}
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


def final_segment(text):
    """주관식 최종 답 부분: 같은 줄에 'Answer: X' 가 있으면 마지막 그것, 없으면 첫 줄 + 마지막 줄(구분선 제외).
    모델은 첫 문장에서 답하고('there are **two sinks**') 설명을 덧붙이거나, 설명 뒤 마지막 줄에서 결론을 낸다."""
    hits = list(ANSWER_LINE.finditer(text))
    if hits:
        return hits[-1].group(1).strip()
    lines = [x.strip() for x in text.strip().splitlines() if x.strip() and not set(x.strip()) <= set("-*#> ")]
    return "\n".join(dict.fromkeys([lines[0], lines[-1]])) if lines else ""


def numbers_in(text):
    vals = [float(x.replace(",", "")) for x in re.findall(r"\d[\d,]*(?:\.\d+)?", text)]
    return vals + [NUMBER_WORDS[w] for w in re.findall(r"[a-z]+", text.lower()) if w in NUMBER_WORDS]


def open_match(golds, segment):
    """정답(끝 마침표 제거)이 최종 답 부분에 있는가. 숫자 정답은 숫자로(쉼표·$ 무시, 영어 숫자 단어 포함), 글자 정답은 대소문자 무시 포함."""
    for g in ([golds] if isinstance(golds, str) else golds):
        g = g.strip()
        g = g[:-1] if g.endswith(".") else g
        try:
            if float(g) in numbers_in(segment):
                return True
        except ValueError:
            if re.search(rf"(?<![a-z]){re.escape(g.lower())}(?![a-z])", segment.lower()):
                return True
    return False


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
    segment = final_segment(text)
    return segment, open_match(row["gold"], segment), "open_final"


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
         *([f"생성 후 `--regrade` 로 다시 채점했다({summary['regraded']['note']}, 판정이 바뀐 응답 "
            f"{summary['regraded']['changed_responses']}개). 원래 결과는 `*.before_regrade`.", ""] if summary.get("regraded") else []),
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
          "주관식은 최종 답 부분(같은 줄의 마지막 `Answer:` 뒤, 없으면 첫 줄 + 마지막 줄)에 정답이 있는지로 비교했다. 정답 끝 마침표는 떼고, "
          "숫자는 쉼표·$ 를 무시하고 영어 숫자 단어(two 등)도 숫자로 읽었다. MMMU 주관식 규칙은 이 데이터의 답 형식에서 "
          "맞은 답의 절반가량을 오답 처리해서 쓰지 않았다. 미추출은 오답으로 셌다.", "",
          "| 그룹 | 답을 뽑은 규칙별 응답 수 |", "|---|---|"]
    for name, g in S.items():
        L.append(f"| {name} | " + ", ".join(f"{k} {v}" for k, v in sorted(g["parse_routes"].items(), key=lambda kv: -kv[1])) + " |")
    L += ["",
          f"모델 로드 {summary['timing']['engine_init_seconds']:.0f}초, 입력 전처리 {summary['timing']['prepare_seconds']:.0f}초는 ① 시간에 넣지 않았다."]
    return "\n".join(L) + "\n"


def regrade(a):
    """저장된 응답을 지금 규칙으로 다시 채점하고 summary.json·REPORT.md 를 다시 쓴다. 원래 파일은 *.before_regrade 로 남긴다."""
    code_dir = a.config.resolve().parent
    P = load_parsers(code_dir)
    rows = {}
    for line in open(a.bench / "bench64.jsonl", encoding="utf-8"):
        r = json.loads(line)
        if r["type"] == "mc":
            r["choices"] = choices_of(r)
        rows[r["id"]] = r
    path = a.out / "responses.jsonl"
    recs = [json.loads(line) for line in open(path, encoding="utf-8")]
    summary = json.loads((a.out / "summary.json").read_text(encoding="utf-8"))
    # 바뀐 개수는 생성 직후의 원래 판정과 비교한다(여러 번 다시 채점해도 같은 기준)
    orig = a.out / "responses.jsonl.before_regrade"
    first = [json.loads(line)["correct"] for line in open(orig, encoding="utf-8")] if orig.exists() else [r["correct"] for r in recs]
    changed = 0
    for rec, was in zip(recs, first):
        pred, ok, route = grade(P, rows[rec["id"]], rec["raw_text"])
        changed += ok != was
        rec.update(pred=pred, correct=ok, parse_route=route)
    for name in ("responses.jsonl", "summary.json", "REPORT.md"):
        src = a.out / name
        if src.exists() and not (a.out / f"{name}.before_regrade").exists():
            src.rename(a.out / f"{name}.before_regrade")
    with open(path, "w", encoding="utf-8") as f:
        for rec in recs:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    n, max_tokens, old = summary["n"], summary["max_tokens"], summary["groups"]
    sources = sorted({r["source"] for r in recs})
    groups = {s: summarize([r for r in recs if r["source"] == s], n, max_tokens, old[s]["seconds"]) for s in sources}
    for (source, qtype) in sorted({(r["source"], r["type"]) for r in recs}):
        part = [r for r in recs if r["source"] == source and r["type"] == qtype]
        if len(part) < sum(r["source"] == source for r in recs):
            groups[f"{source} / {qtype}"] = summarize(part, n, max_tokens)
    groups["전체"] = summarize(recs, n, max_tokens, sum(groups[s]["seconds"] for s in sources))
    summary["groups"] = groups
    summary["regraded"] = {"changed_responses": changed, "note": "주관식을 최종 답 부분 단순 비교로 다시 채점"}
    (a.out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1, default=str) + "\n", encoding="utf-8")
    (a.out / "REPORT.md").write_text(report(summary), encoding="utf-8")
    print(f"regraded: {changed} responses changed")
    print(report(summary))


SAMPLING_FIELDS = ("temperature", "top_p", "top_k", "min_p", "presence_penalty", "frequency_penalty",
                   "repetition_penalty", "max_tokens", "skip_special_tokens", "stop_token_ids")


def load_done(path, n):
    """이어 실행: responses.jsonl 에서 rep 0..n-1 이 다 있는 문항만 남기고(끊기며 생긴 깨진 줄·덜 쓴 문항 제거) 그 id 를 돌려준다."""
    if not path.exists():
        return set()
    by_id = collections.defaultdict(dict)
    for line in open(path, encoding="utf-8"):
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        by_id[rec["id"]][rec["rep"]] = rec
    done = [i for i, reps in by_id.items() if set(reps) == set(range(n))]  # 파일 순서 유지
    tmp = path.with_suffix(".jsonl.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        for i in done:
            for k in range(n):
                f.write(json.dumps(by_id[i][k], ensure_ascii=False) + "\n")
    tmp.replace(path)
    return set(done)


def screen(a):
    """GRPO 문제풀 사전 선별용 생성. 응답 + 테스트 A 규칙의 채점 결과를 저장한다(모듈 docstring 참고)."""
    import yaml
    from PIL import Image
    code_dir = a.config.resolve().parent
    sys.path.insert(0, str(code_dir))
    from inputs import load_processor, prepare_inputs
    from vllm_engine import VLLMEngine, sampling_kwargs

    config_bytes = a.config.read_bytes()
    cfg = yaml.safe_load(config_bytes)
    rows = [json.loads(line) for line in open(a.input, encoding="utf-8") if line.strip()]
    if a.limit:
        rows = rows[:a.limit]
    folder = a.input.resolve().parent
    ids = [r["id"] for r in rows]
    if len(set(ids)) != len(ids):
        sys.exit(f"ABORT: {a.input} 에 중복 id 가 있다")
    bad = [r["id"] for r in rows if not r.get("prompt") or not (folder / r.get("image_path", "")).is_file()]
    if bad:
        sys.exit(f"ABORT: prompt 나 이미지 파일이 없는 문항 {len(bad)}개: {bad[:5]}")
    # 채점(pred/correct/parse_route)은 테스트 A 와 같은 규칙. 객관식 보기 읽기가 실패하는 문항이 있으면 모델을 올리기 전에 멈춘다
    P = load_parsers(code_dir)
    bad = []
    for r in rows:
        if r.get("type") == "mc":
            try:
                r["choices"] = choices_of(r)
            except (ValueError, KeyError) as e:
                bad.append(f"{r['id']}: {e}")
    if bad:
        sys.exit(f"ABORT: 객관식 보기를 읽지 못한 문항 {len(bad)}개: {bad[:5]}")

    a.out.mkdir(parents=True, exist_ok=True)
    info_path = a.out / "run_info.json"
    run_key = {"input": a.input.name, "input_sha256": hashlib.sha256(a.input.read_bytes()).hexdigest(),
               "limit": a.limit, "n": a.n, "seed_offset": a.seed_offset, "max_tokens": a.max_tokens or None,
               "config_sha256": hashlib.sha256(config_bytes).hexdigest()}
    if info_path.exists():
        old = json.loads(info_path.read_text(encoding="utf-8"))["run"]
        if old != run_key:
            sys.exit(f"ABORT: {a.out} 에 다른 설정으로 돌린 결과가 있다. 이어 실행하려면 같은 인자로, 새로 하려면 다른 --out 으로.\n"
                     f"  기존 {old}\n  지금 {run_key}")
    else:  # 끝나면 결과로 덮어쓴다. 먼저 써 두는 건 중간에 끊겼을 때 이어 실행 인자를 검사하기 위해서다
        info_path.write_text(json.dumps({"run": run_key, "status": "running"}, ensure_ascii=False, indent=1) + "\n",
                             encoding="utf-8")
    path = a.out / "responses.jsonl"
    done = load_done(path, a.n)
    todo = [(i, r) for i, r in enumerate(rows) if r["id"] not in done]
    print(f"=== {a.input.name}: {len(rows)}문항 × {a.n}회, 이미 끝난 문항 {len(done)}, 남은 문항 {len(todo)}", flush=True)

    processor = load_processor(a.model_dir, cfg)
    engine = VLLMEngine(cfg, a.model_dir)
    from vllm import SamplingParams
    import vllm
    base = sampling_kwargs(cfg)
    if a.max_tokens:  # 학습 rollout 상한에 맞출 때(2026-11-10 하경님: 2048). 나머지 생성 설정은 config 그대로
        base["max_tokens"] = a.max_tokens
    first = SamplingParams(**{**base, "seed": base["seed"] + a.seed_offset})
    sampling = {"applied": {k: getattr(first, k) for k in SAMPLING_FIELDS},
                "seed_rule": f"{base['seed']} + seed_offset + 문항 순번(파일 안 0부터) × n + rep (seed_offset·n 은 run_info.json)",
                "max_model_len": engine.kwargs.get("max_model_len"),
                "image_min_pixels": cfg["image"]["min_pixels"], "image_max_pixels": cfg["image"]["max_pixels"],
                "model": cfg["model"], "config_sha256": run_key["config_sha256"], "vllm": vllm.__version__,
                "vllm_plugins_env": os.environ.get("VLLM_PLUGINS"), "sampling_params_repr": repr(first).replace(
                    f"seed={first.seed}", "seed=<요청마다 다름>")}
    (a.out / "sampling_params.json").write_text(json.dumps(sampling, ensure_ascii=False, indent=1, default=str) + "\n",
                                                encoding="utf-8")
    print("sampling", sampling["applied"], flush=True)

    started, gen_seconds = time.monotonic(), 0.0
    with open(path, "a", encoding="utf-8") as f:
        for c0 in range(0, len(todo), a.chunk_items):
            chunk = todo[c0:c0 + a.chunk_items]
            prepared = {}
            for _, r in chunk:
                image = Image.open(folder / r["image_path"])
                image.load()
                messages = [{"role": "user", "content": [
                    {"type": "image", "image": image, "min_pixels": cfg["image"]["min_pixels"],
                     "max_pixels": cfg["image"]["max_pixels"]},
                    {"type": "text", "text": r["prompt"]}]}]
                prepared[r["id"]], sizes = prepare_inputs(messages, processor)
                r["image_size"] = list(sizes[0])
            reqs = [(r, k, base["seed"] + a.seed_offset + i * a.n + k) for i, r in chunk for k in range(a.n)]
            t = time.monotonic()
            outs = engine.llm.generate([dict(prepared[r["id"]]) for r, _, _ in reqs],
                                       [SamplingParams(**{**base, "seed": seed}) for _, _, seed in reqs], use_tqdm=True)
            gen_seconds += time.monotonic() - t
            if len(outs) != len(reqs):
                raise RuntimeError(f"vLLM 출력 {len(outs)}개 != 요청 {len(reqs)}개")
            for (r, k, seed), out in zip(reqs, outs):
                c = out.outputs[0]
                pred, ok, route = grade(P, r, c.text)
                f.write(json.dumps({"id": r["id"], "source": r.get("source"), "subset": r.get("subset"),
                                    "type": r.get("type"), "gold": r.get("gold"), "rep": k, "seed": seed,
                                    "image_size": r["image_size"], "prompt_tokens": len(out.prompt_token_ids),
                                    "output_tokens": len(c.token_ids), "finish_reason": c.finish_reason,
                                    "pred": pred, "correct": ok, "parse_route": route,
                                    "raw_text": c.text}, ensure_ascii=False) + "\n")
            f.flush()
            os.fsync(f.fileno())
            del prepared, outs
            n_done = c0 + len(chunk)
            elapsed = time.monotonic() - started
            print(f"=== {n_done}/{len(todo)}문항 끝, {elapsed / 60:.1f}분 경과, "
                  f"남은 예상 {elapsed / n_done * (len(todo) - n_done) / 60:.0f}분", flush=True)

    recs = [json.loads(line) for line in open(path, encoding="utf-8")]
    toks = [r["output_tokens"] for r in recs]
    by_source = collections.defaultdict(list)
    for r in recs:
        by_source[r["source"]].append(r)
    stats = {s: {"responses": len(g), "output_tokens_sum": sum(x["output_tokens"] for x in g),
                 "length_truncated": sum(x["finish_reason"] == "length" for x in g)} for s, g in sorted(by_source.items(), key=str)}
    info = {"run": run_key, "items": len(rows), "responses": len(recs), "expected_responses": len(rows) * a.n,
            "output_tokens_sum": sum(toks), "output_tokens_median": st.median(toks) if toks else None,
            "length_truncated": sum(r["finish_reason"] == "length" for r in recs), "by_source": stats,
            "timing_this_call": {"engine_init_seconds": engine.init_seconds, "generate_seconds": round(gen_seconds, 1),
                                 "total_seconds": round(time.monotonic() - started, 1), "items_generated": len(todo)},
            "gpu": engine.memory_report(), "engine": engine.describe()}
    info_path.write_text(json.dumps(info, ensure_ascii=False, indent=1, default=str) + "\n", encoding="utf-8")
    print(json.dumps({k: info[k] for k in ("items", "responses", "expected_responses", "output_tokens_sum",
                                           "length_truncated", "timing_this_call")}, ensure_ascii=False, indent=1))
    if len(recs) != len(rows) * a.n:
        sys.exit(f"WARNING: 응답 {len(recs)}개, 기대 {len(rows) * a.n}개")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bench", type=Path, help="bench64.jsonl 과 images/ 가 있는 폴더(테스트 A)")
    ap.add_argument("--input", type=Path, help="사전 선별 생성: 문항 jsonl(bench64 형식)")
    ap.add_argument("--model_dir", type=Path, help="생성할 때 필요(--regrade 면 불필요)")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--config", type=Path, default=REPO / "code" / "config.yaml")
    ap.add_argument("--n", type=int, default=8, help="문항당 생성 횟수")
    ap.add_argument("--limit", type=int, default=0,
                    help="동작 확인용 문항 수 제한(0 = 전부). 테스트 A 는 소스당, --input 은 파일 앞에서부터")
    ap.add_argument("--seed_offset", type=int, default=0, help="--input: seed 에 더할 값(파일끼리 seed 가 겹치지 않게)")
    ap.add_argument("--chunk_items", type=int, default=256, help="--input: 한 번에 생성할 문항 수")
    ap.add_argument("--max_tokens", type=int, default=0, help="--input: 생성 상한(0 = config 값). 나머지 생성 설정은 config 그대로")
    ap.add_argument("--regrade", action="store_true", help="생성 없이 저장된 응답만 다시 채점")
    a = ap.parse_args()
    if bool(a.bench) == bool(a.input):
        ap.error("--bench(테스트 A) 와 --input(사전 선별) 중 하나만 준다")
    if a.regrade:
        if a.input:
            ap.error("--regrade 는 --bench 와 함께 쓴다")
        return regrade(a)
    if a.model_dir is None:
        ap.error("--model_dir 가 필요하다")
    if a.input:
        return screen(a)

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
