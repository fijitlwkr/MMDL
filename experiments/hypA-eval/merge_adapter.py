#!/usr/bin/env python3
"""GRPO LoRA 어댑터(swift 저장본)를 베이스 Qwen3-VL-4B-Instruct 에 병합해 평가용 모델 폴더를 만든다. 파드에서 돌린다.

  python experiments/hypA-eval/merge_adapter.py --adapter_repo MMDL-team4/hypA-grpo-pilot30-ckpt --adapter_rev <sha> \
      --subfolder step30 --config code/config.yaml --out /workspace/hypA_eval/merged/g30

- 베이스는 config.yaml 의 repo_id·revision 으로 받는다. 어댑터의 adapter_config.json·args.json 에 적힌 베이스 경로는
  학습 서버의 로컬 경로라 쓰지 않는다(베이스 모델 객체를 직접 넘긴다).
- 병합 결과 폴더에는 병합된 가중치만 새로 쓰고, config.json·generation_config.json·토크나이저·프로세서·대화 템플릿 파일은
  베이스 폴더의 파일을 그대로 복사한다. 그래서 평가 코드가 보는 설정은 베이스와 같고 가중치만 다르다.
- 확인하는 것 (하나라도 어긋나면 MERGE_OK 를 만들지 않고 멈춘다)
  0. 어댑터와 같이 저장된 swift args.json 의 학습 시작 모델이 이 베이스(이름·snapshot revision)다. 일반 LoRA 다(DoRA 등 아님).
  1. 어댑터 키가 모두 lora_A/lora_B 이고 비전(visual) 쪽 키가 없다.
  2. 어댑터 파일의 텐서가 모델에 하나도 빠짐없이, 값 그대로 올라갔다(이름이 안 맞으면 PEFT 가 경고만 하고 LoRA 가
     0 인 채로 병합되므로 직접 대조한다).
  3. 병합 뒤 저장한 가중치를 베이스와 텐서마다 비교: 바뀐 텐서는 LoRA 를 붙인 언어모델 선형층뿐이고, 비전·임베딩·
     정규화 등 나머지는 비트 단위로 같다.
  4. LoRA 대상 층마다 실제로 더해진 변화(병합본 − 베이스)를 scaling × (B @ A) 와 비교해 기록한다. 병합본은 bf16 이라
     변화가 아주 작으면 반올림으로 일부가 사라진다. 이 오차는 멈추는 조건이 아니라 보고용이다(merge_info.json 의 bf16_merge).
     값이 바뀐 원소가 절반 미만이거나 오차 중앙값이 0.5 를 넘으면 로그에 경고를 찍고 bf16_merge.warning=true 로 남긴다.
- 끝나면 <out>/merge_info.json 과 <out>/MERGE_OK 를 쓴다.
"""
import argparse, hashlib, json, re, shutil, sys
from pathlib import Path

WEIGHT_SUFFIXES = (".safetensors", ".bin", ".pt", ".gguf", ".onnx")
WEIGHT_INDEXES = ("model.safetensors.index.json", "pytorch_model.bin.index.json")


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def tensor_index(model_dir):
    """키 -> 파일 경로 (샤딩 여부와 무관하게)."""
    model_dir = Path(model_dir)
    idx = model_dir / "model.safetensors.index.json"
    if idx.exists():
        return {k: model_dir / f for k, f in json.loads(idx.read_text())["weight_map"].items()}
    from safetensors import safe_open
    out = {}
    for f in sorted(model_dir.glob("*.safetensors")):
        with safe_open(str(f), "pt") as s:
            out.update({k: f for k in s.keys()})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--adapter_repo", required=True)
    ap.add_argument("--adapter_rev", required=True, help="고정 commit sha")
    ap.add_argument("--subfolder", required=True, help="예: step30")
    ap.add_argument("--config", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--skip_base_check", action="store_true",
                    help="args.json 의 학습 시작 모델 확인을 건너뜀(경로 이름만 다르고 원본이 맞다고 확인한 경우에만)")
    a = ap.parse_args()

    import torch, yaml
    import peft, transformers
    from huggingface_hub import snapshot_download
    from peft import PeftModel
    from safetensors import safe_open
    from transformers import AutoModelForImageTextToText

    if (a.out / "MERGE_OK").exists():
        print(f"[skip] 이미 병합됨: {a.out}"); return
    if a.out.exists():
        shutil.rmtree(a.out)
    cfg = yaml.safe_load(a.config.read_text())
    base_repo, base_rev = cfg["model"]["repo_id"], cfg["model"]["revision"]

    # ---- 어댑터 받기·검사
    snap = Path(snapshot_download(a.adapter_repo, revision=a.adapter_rev, allow_patterns=[f"{a.subfolder}/*"]))
    adir = snap / a.subfolder
    afile = adir / "adapter_model.safetensors"
    if not afile.exists():
        sys.exit(f"ABORT: {afile} 없음. 받은 파일: {[str(p.relative_to(snap)) for p in snap.rglob('*') if p.is_file()]}")
    acfg = json.loads((adir / "adapter_config.json").read_text())
    if acfg.get("use_dora") or acfg.get("rank_pattern") or acfg.get("alpha_pattern"):
        sys.exit(f"ABORT: 일반 LoRA 가 아님(use_dora/rank_pattern/alpha_pattern). 병합 검사 방식을 다시 정해야 함: "
                 f"{ {k: acfg.get(k) for k in ('use_dora', 'rank_pattern', 'alpha_pattern')} }")
    # 학습을 어떤 모델에서 시작했는지 swift args.json 으로 확인한다. 원본이 아니면(예: SFT 모델에서 시작) 멈춘다.
    args_file = next((p for p in (adir / "args.json", snap / "args.json") if p.exists()), None)
    train_model = None
    if args_file is None:
        print("주의: args.json 이 없어 학습 시작 모델을 확인하지 못함. 베이스가 원본이라고 가정하고 진행")
    else:
        targs = json.loads(args_file.read_text())
        train_model = str(targs.get("model") or targs.get("model_id_or_path") or "")
        print(f"학습 시작 모델 (args.json): {train_model}  revision: {targs.get('model_revision')}")
        snap_rev = re.search(r"snapshots/([0-9a-f]{40})", train_model)
        if a.skip_base_check:
            print("주의: --skip_base_check 로 학습 시작 모델 확인을 건너뜀")
        elif base_repo.split("/")[-1] not in train_model or (snap_rev and snap_rev.group(1) != base_rev) \
                or (targs.get("model_revision") not in (None, "", base_rev)):
            sys.exit(f"ABORT: 학습 시작 모델이 {base_repo}@{base_rev[:7]} 이 아님: {train_model} "
                     f"(revision {targs.get('model_revision')})")
    with safe_open(str(afile), "pt") as s:
        akeys = list(s.keys())
        adapter = {k: s.get_tensor(k) for k in akeys}
    bad = [k for k in akeys if not (".lora_A." in k or ".lora_B." in k)]
    vis = [k for k in akeys if "visual" in k]
    print(f"adapter {a.adapter_repo}@{a.adapter_rev[:7]}/{a.subfolder}: {len(akeys)} keys, r={acfg.get('r')}, "
          f"alpha={acfg.get('lora_alpha')}, target={acfg.get('target_modules')}, "
          f"base path in adapter_config (무시): {acfg.get('base_model_name_or_path')}")
    if bad or vis:
        sys.exit(f"ABORT: LoRA 가 아닌 키 {len(bad)}개 {bad[:3]}, 비전 키 {len(vis)}개 {vis[:3]}")
    n_lora_b = sum(".lora_B." in k for k in akeys)
    zero_b = sum(".lora_B." in k and not adapter[k].any() for k in akeys)
    print(f"lora_B {n_lora_b}개 중 전부 0 인 것 {zero_b}개")

    # ---- 베이스 받기·불러오기 (CPU, bf16)
    base_dir = Path(snapshot_download(base_repo, revision=base_rev))
    print(f"base {base_repo}@{base_rev[:7]} -> {base_dir}")
    model = AutoModelForImageTextToText.from_pretrained(base_dir, torch_dtype=torch.bfloat16)  # 기본이 CPU
    pm = PeftModel.from_pretrained(model, str(adir), is_trainable=False)

    # ---- 2. 어댑터 텐서가 빠짐없이 값 그대로 올라갔는지
    params = dict(pm.named_parameters())
    missing, differ = [], []
    for k, t in adapter.items():
        name = k.replace(".lora_A.weight", ".lora_A.default.weight").replace(".lora_B.weight", ".lora_B.default.weight")
        p = params.get(name)
        if p is None:
            missing.append(k)
        elif not torch.equal(p.detach().to(t.dtype), t):
            differ.append(k)
    print(f"어댑터 텐서 대조: {len(adapter)}개 중 모델에 없음 {len(missing)}, 값 다름 {len(differ)}")
    if missing or differ:
        sys.exit(f"ABORT: 어댑터가 모델에 제대로 안 올라감. 없음 예 {missing[:3]}, 다름 예 {differ[:3]}")
    targets = sorted({k.split(".lora_A.")[0] for k in akeys if ".lora_A." in k})  # base_model.model.<모듈>
    # 실제 배율은 불러온 모델에서 읽는다(rsLoRA 등이면 alpha/r 이 아니므로)
    scale_of = {t: float(pm.get_submodule(t).scaling["default"]) for t in targets}
    scaling = sorted(set(scale_of.values()))
    print(f"LoRA 배율(scaling): {scaling} (alpha/r = {acfg['lora_alpha'] / acfg['r']})")

    # ---- 병합·저장
    merged = pm.merge_and_unload()
    a.out.mkdir(parents=True)
    merged.save_pretrained(a.out, safe_serialization=True, max_shard_size="5GB")
    for f in base_dir.iterdir():  # 설정·토크나이저·프로세서는 베이스 그대로
        if f.is_file() and not f.name.endswith(WEIGHT_SUFFIXES) and f.name not in WEIGHT_INDEXES:
            shutil.copy2(f, a.out / f.name)
    del merged, pm, model, params

    # ---- 3·4. 저장된 가중치를 베이스와 비교
    bi, mi = tensor_index(base_dir), tensor_index(a.out)
    only_base, only_merged = sorted(set(bi) - set(mi)), sorted(set(mi) - set(bi))
    base_cfg = json.loads((base_dir / "config.json").read_text())
    tied = base_cfg.get("tie_word_embeddings") or (base_cfg.get("text_config") or {}).get("tie_word_embeddings")
    if only_base == ["lm_head.weight"] and not only_merged and tied:
        print("참고: 입력·출력 임베딩 공유(tie_word_embeddings)라 저장본에 lm_head.weight 가 따로 없음. 나머지 키로 비교")
        bi = {k: v for k, v in bi.items() if k != "lm_head.weight"}
    elif only_base or only_merged:
        sys.exit(f"ABORT: 저장된 가중치 키가 베이스와 다름. 베이스에만 {only_base[:3]}, 병합본에만 {only_merged[:3]}")
    target_weights = {t.removeprefix("base_model.model.") + ".weight" for t in targets}
    unknown = sorted(target_weights - set(bi))
    if unknown:
        sys.exit(f"ABORT: LoRA 대상 가중치 이름이 저장본에 없음 {unknown[:3]}")
    # LoRA 대상 층마다: 실제로 더해진 변화(병합본 − 베이스)가 계산상 변화 scaling × (B @ A) 와 얼마나 맞는지.
    # 병합본은 bf16 이라 아주 작은 변화는 반올림으로 사라지거나 커진다. 이 비율을 기록해 둔다(멈추지는 않음).
    changed, wrong_changed, per_layer = [], [], []
    for k in sorted(bi):
        with safe_open(str(bi[k]), "pt") as s:
            b = s.get_tensor(k)
        with safe_open(str(mi[k]), "pt") as s:
            m = s.get_tensor(k)
        if b.shape != m.shape or b.dtype != m.dtype:
            sys.exit(f"ABORT: {k} 모양/형식 다름 {b.shape}/{b.dtype} vs {m.shape}/{m.dtype}")
        same = torch.equal(b, m)
        if not same:
            (changed if k in target_weights else wrong_changed).append(k)
        if k in target_weights:
            mod = "base_model.model." + k.removesuffix(".weight")
            delta = scale_of[mod] * (adapter[mod + ".lora_B.weight"].float() @ adapter[mod + ".lora_A.weight"].float())
            applied = m.float() - b.float()
            dn = delta.norm().item()
            per_layer.append({"tensor": k, "delta_over_weight": dn / b.float().norm().item(),
                              "applied_error": (applied - delta).norm().item() / dn if dn else None,
                              "elements_changed": (applied != 0).float().mean().item()})
    errs = sorted(x["applied_error"] for x in per_layer if x["applied_error"] is not None)
    ratio = sorted(x["delta_over_weight"] for x in per_layer)
    frac = sorted(x["elements_changed"] for x in per_layer)
    med = lambda v: v[len(v) // 2] if v else None
    bf16 = {"delta_over_weight_median": med(ratio), "delta_over_weight_max": ratio[-1] if ratio else None,
            "applied_error_median": med(errs), "applied_error_max": errs[-1] if errs else None,
            "elements_changed_median": med(frac)}
    print(f"가중치 비교: 전체 {len(bi)}개, LoRA 대상 {len(target_weights)}개 중 바뀜 {len(changed)}개, "
          f"대상이 아닌데 바뀜 {len(wrong_changed)}개")
    fmt = lambda v, f: "-" if v is None else format(v, f)
    print(f"LoRA 변화 크기(‖ΔW‖/‖W‖) 중앙 {fmt(bf16['delta_over_weight_median'], '.2e')}, "
          f"최대 {fmt(bf16['delta_over_weight_max'], '.2e')} | "
          f"bf16 저장 후 오차(‖실제−계산‖/‖계산‖) 중앙 {fmt(bf16['applied_error_median'], '.2f')}, "
          f"최대 {fmt(bf16['applied_error_max'], '.2f')} | 값이 바뀐 원소 비율 중앙 {fmt(bf16['elements_changed_median'], '.1%')}")
    # 보고용 표시(멈추지 않음): 학습 변화의 상당 부분이 bf16 반올림으로 사라졌을 수 있다
    bf16["warning"] = bool((bf16["elements_changed_median"] or 0) < 0.5 or (bf16["applied_error_median"] or 0) > 0.5)
    if bf16["warning"]:
        print("경고(bf16): 학습 변화의 상당 부분이 병합본 저장 때 반올림으로 사라졌을 수 있음. 결과 보고에 이 숫자를 같이 적을 것")
    if wrong_changed:
        sys.exit(f"ABORT: LoRA 대상이 아닌 가중치가 바뀜 {wrong_changed[:5]}")
    if not changed:
        sys.exit("ABORT: 바뀐 가중치가 없음(병합이 적용되지 않음)")

    info = {"adapter_repo": a.adapter_repo, "adapter_rev": a.adapter_rev, "subfolder": a.subfolder,
            "adapter_sha256": sha256(afile), "adapter_config": acfg,
            "base_repo": base_repo, "base_rev": base_rev, "scaling": scaling, "train_start_model": train_model,
            "lora_keys": len(akeys), "lora_b_all_zero": zero_b, "target_weights": len(target_weights),
            "changed_weights": len(changed), "bf16_merge": bf16, "per_layer": per_layer,
            "copied_from_base": sorted(f.name for f in base_dir.iterdir() if f.is_file()
                                       and not f.name.endswith(WEIGHT_SUFFIXES) and f.name not in WEIGHT_INDEXES),
            "versions": {"torch": torch.__version__, "transformers": transformers.__version__, "peft": peft.__version__}}
    (a.out / "merge_info.json").write_text(json.dumps(info, ensure_ascii=False, indent=1), encoding="utf-8")
    (a.out / "MERGE_OK").touch()
    print(f"MERGE_OK {a.out}")


if __name__ == "__main__":
    main()
