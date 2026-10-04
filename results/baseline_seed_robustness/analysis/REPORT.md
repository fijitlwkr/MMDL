# Baseline seed robustness - analysis

| arm | group | acc % | correct/900 | MC % | open % | length-finish | acc on length-finish % |
|---|---|---|---|---|---|---|---|
| baseline_seed_3407 | baseline | 66.67 | 600 | 66.12 | 75.47 | 128 | 35.9 |
| rep_draft | repeat | 67.44 | 607 | 66.82 | 77.36 | 108 | 35.2 |
| rep_new_output | repeat | 67.56 | 608 | 66.94 | 77.36 | 114 | 39.5 |
| rescore_baseline | judge | 66.22 | 596 | 65.76 | 73.58 | 128 | 33.6 |
| seed_1234 | seed | 65.89 | 593 | 65.53 | 71.70 | 128 | 35.9 |
| seed_2026 | seed | 66.89 | 602 | 66.59 | 71.70 | 113 | 36.3 |
| seed_42 | seed | 66.22 | 596 | 65.64 | 75.47 | 121 | 38.0 |

## Paired vs baseline (same 900 questions)

| arm | gains | losses | flips (%) | diff pp | 95% CI pp | McNemar p |
|---|---|---|---|---|---|---|
| rep_draft | 52 | 45 | 97 (10.8) | +0.78 | [-1.37, +2.92] | 0.543 |
| rep_new_output | 61 | 53 | 114 (12.7) | +0.89 | [-1.44, +3.21] | 0.512 |
| rescore_baseline | 0 | 4 | 4 (0.4) | -0.44 | [-0.88, -0.01] | 0.125 |
| seed_1234 | 69 | 76 | 145 (16.1) | -0.78 | [-3.40, +1.84] | 0.618 |
| seed_2026 | 56 | 54 | 110 (12.2) | +0.22 | [-2.06, +2.51] | 0.924 |
| seed_42 | 63 | 67 | 130 (14.4) | -0.44 | [-2.93, +2.04] | 0.793 |

Mean flip % vs baseline by group: seed 14.3%, repeat 11.7%, judge 0.4%

## Is the baseline an outlier among independent sampling seeds?

- other seeds (k=3): mean 66.33, sd 0.51, range [65.89, 66.89]
- baseline 66.67 -> +0.33 pp from their mean (z = 0.65)
- 95% prediction interval for one new seed: [63.80, 68.86] -> baseline inside: True
- seeds scoring >= baseline: 1/3
- all 4 runs incl. baseline: mean 66.42 +- 0.45 (sd), range [65.89, 66.89]

## Item-level consistency over 4 runs

- always correct 477, always wrong 192, mixed 231 (25.7%)

## Same-seed repeats (baseline + repeats; different hosts/drivers for rep_*)

- n=3: mean 67.22, sd 0.48, range [66.67, 67.56]

## Pre-registered triggers (README s4)

- Tier 2 (seed_777, seed_31337): not needed
- Tier 3 (ctrl_repeat on this pod): not needed
