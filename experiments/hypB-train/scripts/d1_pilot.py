"""Observe D1 without changing the Stage 1 launcher, template, or objective."""

import json
import math
from pathlib import Path
import re
import statistics
import time

import torch
from transformers import TrainerCallback
import swift.llm
from swift.llm.train.rlhf import SwiftRLHF
from swift.plugin import extra_callbacks

from dpo_train import CONFIG, main


class Observer(TrainerCallback):
    def __init__(self):
        self.ref_scores = []
        self.metrics = []
        self.longest = []

    def write(self, event, **values):
        with self.log.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"event": event, **values}, allow_nan=False) + "\n")

    def on_train_begin(self, args, state, control, **kwargs):
        self.log = Path(args.output_dir) / "pilot_observations.jsonl"
        assert state.max_steps == 20
        self.started = time.monotonic()
        self.write("model", **self.model_evidence)

    def on_step_begin(self, args, state, control, **kwargs):
        torch.cuda.synchronize()
        self.step_started = time.monotonic()
        self.step_epoch = time.time()
        torch.cuda.reset_peak_memory_stats()

    def on_step_end(self, args, state, control, **kwargs):
        torch.cuda.synchronize()
        self.step_observation = {"step": state.global_step, "seconds": time.monotonic() - self.step_started,
                                 "epoch_begin": self.step_epoch, "epoch_end": time.time(),
                                 "allocated_bytes": torch.cuda.max_memory_allocated(),
                                 "reserved_bytes": torch.cuda.max_memory_reserved()}

    def on_log(self, args, state, control, logs=None, **kwargs):
        if not logs or "loss" not in logs:
            return
        keys = ("loss", "grad_norm", "rewards/margins", "rewards/accuracies", "logps/chosen", "logps/rejected", "nll_loss")
        metrics = {key: float(logs[key]) for key in keys}
        assert all(math.isfinite(value) for value in metrics.values()), (state.global_step, metrics)
        assert len(self.ref_scores) == CONFIG["gradient_accumulation_steps"]
        ref_chosen, ref_rejected = zip(*self.ref_scores, strict=True)
        self.ref_scores.clear()
        metrics.update(ref_chosen_logp=statistics.mean(ref_chosen), ref_rejected_logp=statistics.mean(ref_rejected))
        record = {**self.step_observation, **metrics}
        self.metrics.append(record)
        self.write("step", **record)
        print(f"D1_STEP {state.global_step}/20 loss={metrics['loss']:.5f} margin={metrics['rewards/margins']:.5f}", flush=True)

    def validate(self):
        assert [row["step"] for row in self.metrics] == list(range(1, 21))
        assert self.longest == [20], self.longest
        for key in ("rewards/margins", "logps/chosen", "logps/rejected"):
            assert len({row[key] for row in self.metrics}) > 1, f"Flat pilot metric: {key}"
        self.write("complete", steps=20, wall_seconds=time.monotonic() - self.started, longest_steps=self.longest)


class ObservedDPO(SwiftRLHF):
    def train(self, trainer):
        observer = next(callback for callback in self.callbacks if isinstance(callback, Observer))
        model = trainer.accelerator.unwrap_model(trainer.model)
        modules = {name: module for name, module in model.named_modules() if hasattr(module, "lora_A")}
        pattern = r"base_model\.model\." + CONFIG["target_regex"]
        assert len(modules) == 252 and all(re.fullmatch(pattern, name) for name in modules)
        trainable = {name for name, value in model.named_parameters() if value.requires_grad}
        assert trainable == {f"{name}.lora_{side}.default.weight" for name in modules for side in ("A", "B")}
        assert trainer.ref_model is None and trainer.is_peft_model and trainer.ref_adapter_name is None
        assert not trainer.args.reference_free and not trainer.args.disable_dropout
        assert trainer.args.rpo_alpha == 1.0 and trainer.beta == 0.1
        assert all(not module.disable_adapters for module in modules.values())
        with trainer.null_ref_context():
            assert all(module.disable_adapters for module in modules.values())
        assert all(not module.disable_adapters for module in modules.values())
        observer.model_evidence = {"language_lora": len(modules), "vision_lora": 0,
                                   "trainable_tensors": len(trainable), "ref_mode": "M0, adapters disabled",
                                   "modules": sorted(modules)}

        compute_reference = trainer.compute_ref_log_probs
        def observe_reference(batch):
            chosen, rejected = compute_reference(batch)
            values = chosen.detach().mean().item(), rejected.detach().mean().item()
            assert all(math.isfinite(value) for value in values), "Nonfinite reference logp"
            observer.ref_scores.append(values)
            if batch["input_ids"].shape[-1] == 9708:
                lengths = batch["attention_mask"].sum(dim=-1).tolist()
                responses = batch["labels"].ne(-100).sum(dim=-1).tolist()
                assert lengths == [3310, 9708] and responses == [1794, 8192], (lengths, responses)
                step = trainer.state.global_step + 1
                observer.longest.append(step)
                observer.write("longest", step=step, lengths=lengths, response_lengths=responses)
            return chosen, rejected

        get_batch_metrics = trainer.get_batch_loss_metrics
        def observe_batch(*args, **kwargs):
            loss, metrics = get_batch_metrics(*args, **kwargs)
            if not torch.isfinite(loss).item() or not all(math.isfinite(value) for value in metrics.values()):
                raise ValueError(f"Nonfinite D1 microbatch at optimizer step {trainer.state.global_step + 1}")
            return loss, metrics

        trainer.compute_ref_log_probs = observe_reference
        trainer.get_batch_loss_metrics = observe_batch
        result = super().train(trainer)
        observer.validate()
        return result


if __name__ == "__main__":
    extra_callbacks.append(Observer())
    swift.llm.rlhf_main = lambda args: ObservedDPO(args).main()
    main()
