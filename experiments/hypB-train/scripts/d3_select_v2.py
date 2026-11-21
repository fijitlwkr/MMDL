"""Add the fixed all-correct-stratum protection to D3 checkpoint selection."""

import d3_select as previous
from classify_answers import ROOT, write_json


STRATUM = "excluded_correct_4"
ORIGINAL_SELECT = previous.select


def select(measurements):
    result = ORIGINAL_SELECT(measurements)
    baseline = measurements["M0"]["by_stratum"][STRATUM]
    assert baseline["responses"] == 632
    protection = {}
    eligible = []
    excluded = {}
    for name in previous.NAMES[1:]:
        values = measurements[name]["by_stratum"][STRATUM]
        assert values["responses"] == baseline["responses"]
        loss = baseline["correct"] - values["correct"]
        passed = loss * 50 <= baseline["responses"]
        protection[name] = {"correct": values["correct"], "responses": values["responses"],
                            "delta_pp": -100 * loss / baseline["responses"], "passed": passed}
        reasons = []
        if name not in result["eligible"]:
            reasons.append("Overall reward mean below M0")
        if not passed:
            reasons.append("All-correct-stratum reward mean more than 2 percentage points below M0")
        if reasons:
            excluded[name] = reasons
        else:
            eligible.append(name)
    if not eligible:
        result.update(selected=None, reason="No checkpoint satisfies both eligibility conditions")
    elif len(eligible) == 1:
        result.update(selected=eligible[0], reason="Only this checkpoint satisfies both eligibility conditions")
    result.update(eligible=eligible, excluded=excluded, protection_stratum=STRATUM,
                  protection_baseline=baseline, protection=protection, max_stratum_drop_pp=2.0)
    return result


def self_test():
    cases = (
        ("epoch1_higher", ((800, 600), (860, 600), (840, 600)), "epoch1"),
        ("epoch2_higher", ((800, 600), (840, 600), (860, 600)), "epoch2"),
        ("neither_overall_qualifies", ((800, 600), (799, 600), (798, 600)), None),
        ("within_half_point", ((800, 600), (840, 600), (845, 600)), "epoch1"),
        ("exact_half_point", ((800, 600), (840, 600), (846, 600)), "epoch2"),
        ("only_epoch2_qualifies", ((800, 600), (799, 600), (800, 600)), "epoch2"),
        ("higher_overall_but_protection_fails", ((800, 600), (860, 587), (799, 600)), None),
        ("exclude_best_on_protection", ((800, 600), (860, 587), (840, 600)), "epoch2"),
        ("twelve_losses_within_two_pp", ((800, 600), (860, 588), (840, 600)), "epoch1"),
    )
    layers = {str(index): STRATUM if index < 158 else "excluded_correct_0" if index < 191
              else "retain" if index < 236 else "target" for index in range(300)}
    tests = []
    for name, counts, expected in cases:
        measurements = {}
        for model, (total_correct, protected_correct) in zip(previous.NAMES, counts, strict=True):
            assert 0 <= protected_correct <= 632 and 0 <= total_correct - protected_correct <= 568
            fake = []
            for ordinal in range(1200):
                reward = ordinal < protected_correct if ordinal < 632 else ordinal - 632 < total_correct - protected_correct
                fake.append({"row": str(ordinal // 4), "reward": int(reward), "finish_reason": "stop",
                             "output_tokens": 10, "marker_count": 0})
            measurements[model] = previous.metrics(fake, layers)
        actual = select(measurements)
        assert actual["selected"] == expected, (name, actual)
        tests.append({"case": name, "measurements": measurements, "expected": expected,
                      "selection": actual, "passed": True})
    write_json(ROOT / "reports/d3_selection_v2_tests.json", {"status": "PASS", "synthetic": True, "tests": tests})
    print("D3 v2 selection synthetic tests PASS", len(tests))


if __name__ == "__main__":
    previous.select = select
    previous.self_test = self_test
    previous.main()
