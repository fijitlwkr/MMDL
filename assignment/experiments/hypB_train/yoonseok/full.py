"""Run an independent full E1/E2 epoch with the validated measurement callback."""
import sys

import torch
from swift.plugin import extra_callbacks
from pilot import PilotObserver
from train import main


if __name__ == "__main__":
    assert len(sys.argv) == 5 and sys.argv[1] in {"E1", "E2"} and sys.argv[2] == "full"
    torch.cuda.reset_peak_memory_stats()
    observer = PilotObserver()
    observer.expected_steps = 188
    observer.observation_filename = "training_observations.jsonl"
    extra_callbacks.append(observer)
    main()
