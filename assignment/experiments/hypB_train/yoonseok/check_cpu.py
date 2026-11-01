"""Compare swift training IDs and labels with the pinned evaluation processor."""
import argparse
import json
import os
from pathlib import Path
from train import CONFIG, HERE, image_env


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data", type=Path)
    parser.add_argument("processor", type=Path, help="local pinned processor snapshot")
    args = parser.parse_args()
    model_dir = args.processor.resolve()
    os.chdir(args.data)
    os.environ.update(CUDA_VISIBLE_DEVICES="-1", HF_HUB_OFFLINE="1", MODELSCOPE_OFFLINE="1")
    image_env()
    from swift.llm import get_model_tokenizer, get_template, load_dataset
    from qwen_vl_utils import process_vision_info
    import torch
    torch.set_num_threads(4)
    model, processor = get_model_tokenizer(str(model_dir), model_type=CONFIG["model_type"],
                                          load_model=False, use_hf=True)
    assert model is None
    template = get_template(CONFIG["template"], processor, max_length=CONFIG["max_length"],
                            loss_scale=CONFIG["loss_scale"])
    template.set_mode("train")
    errors = []
    expected = json.loads((HERE / "pilot_expected.json").read_text())
    for run in ("E1", "E2"):
        rows, _ = load_dataset(str(Path(f"{run}_train_swift.jsonl").resolve()),
                               strict=True, use_hf=True, shuffle=False)
        for ref in (r for r in expected if r["run"] == run):
            row = rows[ref["row"]]
            assert [image["path"] for image in row["images"]] == [ref["image"]]
            user, answer = row["messages"]
            text = user["content"]
            assert text.startswith("<image>")
            messages = [{"role": "user", "content": [
                {"type": "image", "image": ref["image"], "min_pixels": 1003520, "max_pixels": 4014080},
                {"type": "text", "text": text.removeprefix("<image>")}]}]
            images, _ = process_vision_info(messages, image_patch_size=16)
            def reference_ids(chat, generation_prompt):
                rendered = processor.apply_chat_template(chat, tokenize=False,
                                                         add_generation_prompt=generation_prompt)
                return processor(text=[rendered], images=images, do_resize=False)["input_ids"][0]
            prompt = reference_ids(messages, True)
            if run == "E1":
                response = processor.tokenizer.encode(
                    answer["content"] + "<|im_end|>\n", add_special_tokens=False)
                reference = prompt + response
                assert prompt[-1] == 198 and response[0] == 271
            else:
                reference = reference_ids(messages + [answer], False)
            encoded = template.encode(row)
            ids, labels = encoded["input_ids"], encoded["labels"]
            masked = labels.count(-100)
            counts = (len(ids), ids.count(processor.image_token_id), masked, len(labels) - masked)
            target = tuple(ref[k] for k in ("total_tokens", "image_pad_tokens", "prompt_tokens",
                                            "assistant_label_tokens"))
            boundary = len(prompt)
            ok = (counts == target and ids == reference and ids[:boundary] == prompt
                  and masked == boundary
                  and labels == [-100] * boundary + reference[boundary:])
            if run == "E1":
                ok = ok and ids[boundary-1:boundary+1] == [198, 271]
            print(run, ref["row"], counts, "OK" if ok else f"FAIL expected {target}", flush=True)
            print("  boundary", ids[boundary-1:boundary+1],
                  "prompt IDs match", ids[:boundary] == prompt,
                  "full IDs match", ids == reference, flush=True)
            if not ok:
                print("  assistant boundary (last 3 prompt IDs + next 3 IDs):",
                      "evaluation", reference[boundary-3:boundary+3],
                      "swift", ids[boundary-3:boundary+3],
                      "labels", labels[boundary-3:boundary+3])
                errors.append((run, ref["row"]))
    if errors:
        raise SystemExit(f"mismatched rows: {errors}")


if __name__ == "__main__":
    main()
