"""Baseline(M0) 4회 실행의 문항별 일관성 진단. 기존 채점 결과만 읽는다 (GPU·API 없음, 학습 자료로 쓰지 않음).

입력: 팀 baseline 시드 실험 3회(sampling seed 42/1234/2026, 브랜치 exp/baseline-seed-robustness)와 우리 M0(seed 3407)의 v2 판정.
출력: reports/baseline_consistency.json
"""
import collections as C, itertools, json, subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT.parent
REPO = WORK / "hypB-train-git"
M0 = WORK / "team-evaluator-no-length/assignment/experiments/raw_evaluation/outputs/release-v2-latest/final_results.jsonl"


def rows(text):
    return {r["id"]: r for r in map(json.loads, text.splitlines())}


def team(seed):
    path = f"origin/exp/baseline-seed-robustness:results/baseline_seed_robustness/seed_{seed}/item_results.jsonl"
    return rows(subprocess.run(["git", "-C", str(REPO), "show", path], capture_output=True, check=True).stdout.decode("utf-8"))


runs = {"42": team(42), "1234": team(1234), "2026": team(2026), "3407": rows(M0.read_text(encoding="utf-8"))}
names = list(runs)
ids = sorted(runs["42"])
assert len(ids) == 900 and all(sorted(r) == ids for r in runs.values())
ok = lambda n, i: bool(runs[n][i]["final_correct"])
cut = lambda n, i: runs[n][i]["finish_reason"] == "length"


def vote(sel):
    total = 0
    for i in ids:
        if runs[sel[0]][i]["question_type"] == "multiple-choice":
            answers = {n: runs[n][i].get("final_answer") for n in sel}
            count = C.Counter(a for a in answers.values() if a)
            if not count:
                continue
            top = max(count.values())
            tops = [a for a, v in count.items() if v == top]
            right = {a: ok(n, i) for n, a in answers.items() if a}
            total += sum(right[a] for a in tops) / len(tops)
        else:
            k = sum(ok(n, i) for n in sel)
            total += 1 if 2 * k > len(sel) else 0.5 if 2 * k == len(sel) else 0
    return round(total / 9, 2)


correct_count = C.Counter(sum(ok(n, i) for n in names) for i in ids)
cut_count = C.Counter(sum(cut(n, i) for n in names) for i in ids)
mixed = [i for i in ids if 0 < sum(cut(n, i) for n in names) < 4]
cut_runs = [ok(n, i) for i in mixed for n in names if cut(n, i)]
done_runs = [ok(n, i) for i in mixed for n in names if not cut(n, i)]
always = [i for i in ids if all(cut(n, i) for n in names)]
never_right = C.Counter(runs["42"][i]["subject"] for i in ids if not any(ok(n, i) for n in names))
unstable = C.Counter(runs["42"][i]["subject"] for i in ids if 0 < sum(ok(n, i) for n in names) < 4)
result = {
    "runs": names,
    "correct_per_run": {n: sum(ok(n, i) for i in ids) for n in names},
    "length_per_run": {n: sum(cut(n, i) for i in ids) for n in names},
    "mean_single_accuracy": round(sum(k * v for k, v in correct_count.items()) / 36, 2),
    "items_by_correct_runs_0_to_4": [correct_count[k] for k in range(5)],
    "plurality_vote_4_runs": vote(names),
    "plurality_vote_3_runs": {"+".join(c): vote(list(c)) for c in itertools.combinations(names, 3)},
    "correct_at_least_once": round((900 - correct_count[0]) / 9, 2),
    "items_by_truncated_runs_0_to_4": [cut_count[k] for k in range(5)],
    "sometimes_truncated_items": {"items": len(mixed),
                                  "truncated_runs": {"n": len(cut_runs), "correct": sum(cut_runs), "pct": round(sum(cut_runs) / len(cut_runs) * 100, 1)},
                                  "completed_runs": {"n": len(done_runs), "correct": sum(done_runs), "pct": round(sum(done_runs) / len(done_runs) * 100, 1)}},
    "always_truncated_items": {"items": len(always), "correct": sum(ok(n, i) for i in always for n in names), "of": 4 * len(always)},
    "never_correct_by_subject": dict(never_right.most_common()),
    "unstable_by_subject": dict(unstable.most_common()),
}
(ROOT / "reports/baseline_consistency.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps(result, ensure_ascii=False, indent=1))
