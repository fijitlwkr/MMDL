"""E1 20-step pilot with parameter, timing and memory checks."""
import json
import re
import time
from pathlib import Path

import torch
from transformers import TrainerCallback
from swift.plugin import extra_callbacks
from train import CONFIG, main


class PilotObserver(TrainerCallback):
    expected_steps = 20
    observation_filename = "pilot_observations.jsonl"

    def record(self, event, **values):
        payload = {"event": event, **values}
        with self.log.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(payload) + "\n")
        print("PILOT", json.dumps(payload), flush=True)

    def on_train_begin(self, args, state, control, model=None, optimizer=None, **kwargs):
        assert state.max_steps == self.expected_steps
        self.log = Path(args.output_dir) / self.observation_filename
        self.started = time.monotonic()
        modules = [name for name, module in model.named_modules() if hasattr(module, "lora_A")]
        trainable = [name for name, param in model.named_parameters() if param.requires_grad]
        allowed = {name + ".lora_" + side + ".default.weight"
                   for name in modules for side in ("A", "B")}
        pattern = "base_model\\.model\\." + CONFIG["target_regex"]
        assert len(modules) == 252 and all(re.fullmatch(pattern, name) for name in modules), modules
        assert set(trainable) == allowed and len(trainable) == 504, trainable
        for group in optimizer.param_groups:
            assert group["betas"] == (0.9, 0.999) and group["eps"] == 1e-8
            assert group["weight_decay"] == 0
        self.record("parameters", lora_modules=modules, trainable_parameters=trainable,
                    visual_trainable=0, optimizer_betas=[0.9, 0.999], optimizer_eps=1e-8)

    def on_step_begin(self, args, state, control, **kwargs):
        torch.cuda.synchronize()
        self.step_started = time.monotonic()

    def on_step_end(self, args, state, control, **kwargs):
        torch.cuda.synchronize()
        self.record("step", step=state.global_step, seconds=time.monotonic() - self.step_started,
                    max_allocated_bytes=torch.cuda.max_memory_allocated(),
                    max_reserved_bytes=torch.cuda.max_memory_reserved())

    def on_evaluate(self, args, state, control, metrics=None, **kwargs):
        self.record("eval", step=state.global_step, metrics=metrics)

    def on_train_end(self, args, state, control, **kwargs):
        torch.cuda.synchronize()
        assert state.global_step == self.expected_steps
        self.record("complete", steps=state.global_step,
                    wall_seconds=time.monotonic() - self.started,
                    max_allocated_bytes=torch.cuda.max_memory_allocated(),
                    max_reserved_bytes=torch.cuda.max_memory_reserved())


if __name__ == "__main__":
    torch.cuda.reset_peak_memory_stats()
    extra_callbacks.append(PilotObserver())
    main()
