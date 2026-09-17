# MMMU truncation budget comparison

| Budget | Correct / subset | Accuracy |
|---|---:|---:|
| Original (2048 / 9048) | 55 / 230 | 23.91% |
| Expanded (8192 / 16384) | 88 / 230 | 38.26% |

Accuracy delta: +14.35%; paired exact McNemar p=0.000112269 (significant at 0.05: True).

| Outcome transition | Items |
|---|---:|
| Incorrect → correct | 52 |
| Correct → incorrect | 19 |
| Both correct | 36 |
| Both incorrect | 123 |

## Per-subject comparison

| Subject | N | Original | Expanded | Delta |
|---|---:|---:|---:|---:|
| Accounting | 15 | 33.33% | 53.33% | +20.00% |
| Agriculture | 0 | — | — | — |
| Architecture_and_Engineering | 25 | 28.00% | 16.00% | -12.00% |
| Art | 0 | — | — | — |
| Art_Theory | 0 | — | — | — |
| Basic_Medical_Science | 1 | 100.00% | 100.00% | +0.00% |
| Biology | 3 | 0.00% | 66.67% | +66.67% |
| Chemistry | 15 | 20.00% | 33.33% | +13.33% |
| Clinical_Medicine | 2 | 0.00% | 50.00% | +50.00% |
| Computer_Science | 10 | 20.00% | 30.00% | +10.00% |
| Design | 0 | — | — | — |
| Diagnostics_and_Laboratory_Medicine | 1 | 0.00% | 100.00% | +100.00% |
| Economics | 5 | 0.00% | 40.00% | +40.00% |
| Electronics | 19 | 42.11% | 31.58% | -10.53% |
| Energy_and_Power | 23 | 30.43% | 65.22% | +34.78% |
| Finance | 10 | 30.00% | 40.00% | +10.00% |
| Geography | 8 | 0.00% | 12.50% | +12.50% |
| History | 1 | 0.00% | 0.00% | +0.00% |
| Literature | 0 | — | — | — |
| Manage | 5 | 0.00% | 40.00% | +40.00% |
| Marketing | 1 | 0.00% | 100.00% | +100.00% |
| Materials | 21 | 28.57% | 23.81% | -4.76% |
| Math | 14 | 21.43% | 50.00% | +28.57% |
| Mechanical_Engineering | 19 | 10.53% | 36.84% | +26.32% |
| Music | 15 | 6.67% | 20.00% | +13.33% |
| Pharmacy | 6 | 66.67% | 100.00% | +33.33% |
| Physics | 5 | 40.00% | 40.00% | +0.00% |
| Psychology | 2 | 0.00% | 0.00% | +0.00% |
| Public_Health | 4 | 25.00% | 50.00% | +25.00% |
| Sociology | 0 | — | — | — |

## Remaining truncation

`finish_reason=length` after expansion: 104/230 (45.22%).

## Potential full-set impact

Replacing only these subset outcomes projects the 900-item score from 410/900 (45.56%) to 443/900 (49.22%), a +3.67% point change. This is a replacement projection, not a fresh 900-item rerun.

Experiment A left 26 judge failures, of which 25 (96.15%) had `finish_reason=length`; the observed subset result indicates how much generation-budget expansion can address that failure mode.
