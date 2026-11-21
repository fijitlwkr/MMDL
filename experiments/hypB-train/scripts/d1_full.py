"""Record the full D1 run through the same trainer and observer as the pilot."""

import math
import os
from pathlib import Path
import statistics
import time

import swift.llm
from swift.plugin import extra_callbacks

from d1_pilot import ObservedDPO, Observer
from dpo_train import CONFIG, main


PAIRS = 707
BATCH = CONFIG["gradient_accumulation_steps"]
STEPS_PER_EPOCH = math.ceil(PAIRS / BATCH)
TOTAL_STEPS = STEPS_PER_EPOCH * CONFIG["num_train_epochs"]


class FullObserver(Observer):
    def on_train_begin(self, args, state, control, **kwargs):
        self.log = Path(args.output_dir) / "full_observations.jsonl"
        assert args.max_steps == -1 and state.max_steps == TOTAL_STEPS and args.num_train_epochs == 2
        assert os.environ.get("PYTORCH_CUDA_ALLOC_CONF") == "expandable_segments:True"
        self.started = time.monotonic()
        self.seen = 0
        self.write("model", **self.model_evidence, cuda_alloc_conf=os.environ["PYTORCH_CUDA_ALLOC_CONF"],
                   max_steps=args.max_steps, epochs=args.num_train_epochs)

    def on_log(self, args, state, control, logs=None, **kwargs):
        if not logs or "loss" not in logs:
            return
        step = state.global_step
        keys = ("loss", "grad_norm", "rewards/margins", "rewards/accuracies", "logps/chosen", "logps/rejected", "nll_loss")
        metrics = {key: float(logs[key]) for key in keys}
        assert all(math.isfinite(value) for value in metrics.values()), (step, metrics)
        expected = (PAIRS % BATCH or BATCH) if step % STEPS_PER_EPOCH == 0 else BATCH
        assert len(self.ref_scores) == expected, (step, len(self.ref_scores), expected)
        ref_chosen, ref_rejected = zip(*self.ref_scores, strict=True)
        self.ref_scores.clear()
        self.seen += expected
        record = {**self.step_observation, **metrics, "epoch": state.epoch, "pairs": expected,
                  "ref_chosen_logp": statistics.mean(ref_chosen), "ref_rejected_logp": statistics.mean(ref_rejected)}
        self.metrics.append(record)
        self.write("step", **record)
        print(f"D1_FULL_STEP {step}/{TOTAL_STEPS} loss={metrics['loss']:.5f} margin={metrics['rewards/margins']:.5f}", flush=True)

    def validate(self):
        assert [row["step"] for row in self.metrics] == list(range(1, TOTAL_STEPS + 1))
        assert self.metrics[-1]["epoch"] == 2 and self.seen == PAIRS * 2
        assert self.longest == [20, 20 + STEPS_PER_EPOCH], self.longest
        self.write("complete", steps=TOTAL_STEPS, pairs=self.seen, wall_seconds=time.monotonic() - self.started,
                   longest_steps=self.longest)


if __name__ == "__main__":
    extra_callbacks.append(FullObserver())
    swift.llm.rlhf_main = lambda args: ObservedDPO(args).main()
    main()
