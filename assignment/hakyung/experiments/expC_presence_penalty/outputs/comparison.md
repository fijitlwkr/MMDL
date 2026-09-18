# Presence penalty comparison

Stratified subset seed: `20260917` (model/sampling seed: `42`)

| presence_penalty | Correct / 200 | Accuracy | Mean output tokens | Parse failures | Length truncations |
|---:|---:|---:|---:|---:|---:|
| 0 | 98 / 200 | 49.00% | 885.08 | 26 (13.00%) | 54 (27.00%) |
| 0.5 | 101 / 200 | 50.50% | 875.76 | 25 (12.50%) | 57 (28.50%) |
| 1.5 (exp0 reused) | 102 / 200 | 51.00% | 869.71 | 16 (8.00%) | 55 (27.50%) |

## Per-subject accuracy

| Subject | N | penalty 0 | penalty 0.5 | penalty 1.5 |
|---|---:|---:|---:|---:|
| Accounting | 7 | 28.57% | 28.57% | 14.29% |
| Agriculture | 6 | 16.67% | 33.33% | 16.67% |
| Architecture_and_Engineering | 6 | 33.33% | 16.67% | 50.00% |
| Art | 7 | 28.57% | 42.86% | 42.86% |
| Art_Theory | 7 | 42.86% | 57.14% | 57.14% |
| Basic_Medical_Science | 6 | 83.33% | 100.00% | 100.00% |
| Biology | 7 | 71.43% | 57.14% | 28.57% |
| Chemistry | 7 | 28.57% | 42.86% | 42.86% |
| Clinical_Medicine | 7 | 57.14% | 85.71% | 71.43% |
| Computer_Science | 7 | 42.86% | 28.57% | 42.86% |
| Design | 7 | 57.14% | 71.43% | 57.14% |
| Diagnostics_and_Laboratory_Medicine | 7 | 57.14% | 57.14% | 57.14% |
| Economics | 7 | 71.43% | 57.14% | 57.14% |
| Electronics | 6 | 33.33% | 50.00% | 66.67% |
| Energy_and_Power | 7 | 42.86% | 28.57% | 57.14% |
| Finance | 6 | 33.33% | 50.00% | 66.67% |
| Geography | 7 | 57.14% | 28.57% | 42.86% |
| History | 7 | 71.43% | 85.71% | 85.71% |
| Literature | 7 | 57.14% | 57.14% | 57.14% |
| Manage | 7 | 57.14% | 71.43% | 42.86% |
| Marketing | 7 | 71.43% | 57.14% | 71.43% |
| Materials | 6 | 16.67% | 33.33% | 33.33% |
| Math | 7 | 28.57% | 42.86% | 14.29% |
| Mechanical_Engineering | 7 | 28.57% | 42.86% | 28.57% |
| Music | 7 | 14.29% | 0.00% | 0.00% |
| Pharmacy | 6 | 50.00% | 50.00% | 66.67% |
| Physics | 6 | 83.33% | 66.67% | 66.67% |
| Psychology | 6 | 66.67% | 50.00% | 66.67% |
| Public_Health | 7 | 71.43% | 71.43% | 71.43% |
| Sociology | 6 | 66.67% | 50.00% | 66.67% |

## Trend check

- Lower penalty → non-longer mean response: `False`
- Lower penalty → non-higher parse failure rate: `False`
- Lower penalty → non-higher length truncation rate: `False`

Conclusion: the hypothesis that lower presence_penalty shortens responses and reduces both parse failures and length truncation is not supported by all three observed monotonic checks; see the numeric table above.

exp0 had 230/900 (25.56%) length truncations. Experiment B tests whether increasing the token budget rescues that group; this experiment instead keeps the original 2048/9048 budget and measures whether lowering presence_penalty reduces response length, parse failures, and truncation.
