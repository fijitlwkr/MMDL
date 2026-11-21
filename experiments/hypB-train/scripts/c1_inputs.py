"""Evaluation image/chat encoding and shared, boundary-tokenized C1 responses."""
from pathlib import Path

from c1_prepare import ROOT, WORKSPACE

PROCESSOR = WORKSPACE / 'work/train_data_B_20261023/final_v5/cache/qwen3_vl_4b_ebb281ec'


def load_processor(path=PROCESSOR):
    from transformers import AutoProcessor
    processor = AutoProcessor.from_pretrained(Path(path).resolve(strict=True), local_files_only=True)
    assert processor.image_processor.patch_size == 16
    assert processor.image_processor.merge_size == 2
    assert processor.tokenizer.convert_tokens_to_ids('<|im_end|>') == processor.tokenizer.eos_token_id
    return processor


def messages(entry, text, cfg, image_root=WORKSPACE):
    images = []
    for im in entry['images']:
        path = (image_root / im['path']).resolve(strict=True)
        assert path.is_relative_to(image_root.resolve())
        images.append({'type': 'image', 'image': str(path), 'min_pixels': cfg['min_pixels'], 'max_pixels': cfg['max_pixels']})
    assert images
    return [{'role': 'user', 'content': images + [{'type': 'text', 'text': text}]}]


def teacher_text(prompt, anchor, cfg):
    return prompt + cfg['teacher_prompt_suffix'].replace('{anchor}', anchor)


def prefixes(entry, anchor, processor, cfg, image_root=WORKSPACE, identical_teacher=False):
    import torch
    from frozen_generation.inputs import prepare_inputs
    student_messages = messages(entry, entry['prompt'], cfg, image_root)
    prepared, sizes = prepare_inputs(student_messages, processor)
    images = prepared['multi_modal_data']['image']
    text = entry['prompt'] if identical_teacher else teacher_text(entry['prompt'], anchor['raw_text'], cfg)
    teacher_messages = messages(entry, text, cfg, image_root)
    teacher_prompt = processor.apply_chat_template(teacher_messages, tokenize=False, add_generation_prompt=True)
    try:
        student = processor(text=[prepared['prompt']], images=images, do_resize=False, return_tensors='pt')
        teacher = processor(text=[teacher_prompt], images=images, do_resize=False, return_tensors='pt')
    finally:
        for image in images:
            image.close()
    assert torch.equal(student['image_grid_thw'], teacher['image_grid_thw'])
    assert torch.equal(student['pixel_values'], teacher['pixel_values'])
    image_id = processor.image_token_id
    assert (student['input_ids'] == image_id).sum() == (teacher['input_ids'] == image_id).sum()
    for batch in (student, teacher):
        assert batch['input_ids'].shape[0] == 1
        assert bool((batch['attention_mask'] == 1).all())
    return student, teacher, {'student_prompt': prepared['prompt'], 'teacher_prompt': teacher_prompt,
                              'teacher_user_text': text, 'resized_sizes': sizes,
                              'image_tokens': int((student['input_ids'] == image_id).sum())}


def response_ids(entry, tokenizer, cfg):
    assert entry['finish_reason'] in ('stop', 'length')
    original = tokenizer.encode(entry['raw_text'], add_special_tokens=False)
    if not original:
        raise ValueError('Empty response token sequence')
    cap = cfg['max_response_tokens']
    ids = original[:cap]
    eos = entry['finish_reason'] == 'stop' and len(original) <= cap
    if eos:
        ids = ids + [tokenizer.eos_token_id]
    return ids, {'retokenized_content_tokens': len(original), 'kept_content_tokens': min(len(original), cap),
                 'eos_added': eos, 'content_was_capped': len(original) > cap}


def append_response(prefix, ids, device=None):
    import torch
    batch = dict(prefix)
    start = batch['input_ids'].shape[1]
    target = torch.tensor([ids], dtype=torch.long, device=batch['input_ids'].device)
    batch['input_ids'] = torch.cat((batch['input_ids'], target), dim=1)
    batch['attention_mask'] = torch.cat((batch['attention_mask'], torch.ones_like(target)), dim=1)
    if device is not None:
        batch = {key: value.to(device) if hasattr(value, 'to') else value for key, value in batch.items()}
        target = target.to(device)
    positions = torch.arange(start - 1, start + len(ids) - 1, device=batch['input_ids'].device)
    assert positions.numel() == len(ids) and positions[0] >= 0
    assert torch.equal(batch['input_ids'][:, start:], target)
    return batch, positions, target
