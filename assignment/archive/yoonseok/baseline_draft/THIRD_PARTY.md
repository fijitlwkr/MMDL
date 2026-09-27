# Third-party code

The `vendor/` directory is required for standalone execution.

- `vendor/mmmu_eval.py`: unchanged from [MMMU](https://github.com/MMMU-Benchmark/MMMU/blob/51ce7f3e829c16bb44bc5445782686b4c3508794/eval/eval_utils.py), commit `51ce7f3e829c16bb44bc5445782686b4c3508794`. Apache-2.0; see `vendor/MMMU-LICENSE`.
- `vendor/vlmevalkit_matching.py`: from [VLMEvalKit](https://github.com/open-compass/VLMEvalKit/blob/f71d47360cb884eee041f280c8e8095b6b051251/vlmeval/utils/matching_util.py), commit `f71d47360cb884eee041f280c8e8095b6b051251`. See `vendor/VLMEvalKit-LICENSE`. The toolkit logger import is replaced with the Python standard library logger; parser logic is unchanged.
- `mc_parsers.py` wraps those functions to record fallback use, isolate the random generator, stabilize open-answer JSON ordering, and fix the VLMEvalKit `VERBOSE` environment to unset during parsing.

MMMU's MC parser uses a random choice if no answer can be extracted. This package preserves that policy with a seeded generator following input order. VLMEvalKit comparison uses only rule extraction; it does not invoke an LLM judge. These are different scoring policies and their differences are recorded in the outputs.
