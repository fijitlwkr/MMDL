# Image layout comparison

Multi-image subset: 23/900 questions.

| Layout | Correct / 23 | Accuracy | Parse failures |
|---|---:|---:|---:|
| inline | 9 / 23 | 39.13% | 3 (13.04%) |
| prefix | 10 / 23 | 43.48% | 6 (26.09%) |

## Paired outcome changes

Flipped questions: 5.

- Inline only correct: 2
- Prefix only correct: 3
- Exact two-sided McNemar p-value: 1

| Question ID | Subject | Inline correct | Prefix correct |
|---|---|---:|---:|
| Art_Theory__validation_Art_Theory_27 | Art_Theory | False | True |
| Clinical_Medicine__validation_Clinical_Medicine_13 | Clinical_Medicine | False | True |
| History__validation_History_15 | History | True | False |
| Manage__validation_Manage_20 | Manage | False | True |
| Music__validation_Music_21 | Music | True | False |

## Conclusion

No statistically significant accuracy difference between the layouts was detected at alpha=0.05.

Caveat: the sample size is small (n=23), so statistical power is low; a non-significant result is not evidence that the layouts are equivalent.
