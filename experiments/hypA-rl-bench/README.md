# 가설 A RL(GRPO) 사전 테스트

RL(GRPO) 학습의 규모와 비용을 정하기 전에 두 가지를 잰다. 모델은 원본 `Qwen/Qwen3-VL-4B-Instruct`(학습 안 한 것), 데이터는 bench64(`MMDL-team4/hypA-rl-bench64`, 64문항)다.

| 테스트 | 하는 일 | 기록 |
|---|---|---|
| A. 생성 속도 | 64문항 × 8회 = 512회 생성 (평가 설정 그대로, 요청마다 seed 다름) | 소스별 ① 시간 ② 생성 토큰 합 ③ 1024/2048/4096/8192 초과 비율 ④ 문항별 정답 횟수(0~8) 분포 ⑤ 문항별 서로 다른 응답 수 |
| B. GRPO 스모크 | ms-swift GRPO + LoRA r16(LLM 만), vLLM colocate, 16문항 × 8회, 4스텝, max_completion_length 2048, overlong_filter 켬 | ① 스텝당 시간 ② 최대 VRAM ③ 성공/실패와 에러 전문 ④ 평균 보상 + 첫 롤아웃 프롬프트를 평가 입력과 비교 |

| 파일 | 내용 |
|---|---|
| `setup.sh` | 팀 고정 버전 설치 → ms-swift 4.6.0(+trl 0.29.1, datasets 4.8.4) 설치 → pip check·import 확인 → bench64 받기·체크섬 검사 → 모델 받기 |
| `test_a_generate.py` | 테스트 A. `code/` 의 `VLLMEngine`·`sampling_kwargs`·`prepare_inputs`·`config.yaml` 을 그대로 쓴다 |
| `test_b_grpo.sh` | 테스트 B. `swift rlhf` 실행 + VRAM 기록 + 프롬프트 비교 + 결과 정리 |
| `test_b_plugin.py` | 테스트 B 의 swift 플러그인(임시 보상, 첫 프롬프트 덤프, overlong 로그)과 보조 명령(prepare / compare / summarize) |

## 순서 (RunPod)

1. 파드를 켠다. **RTX 6000 Ada 48GB**(없으면 RTX 4090), 템플릿 PyTorch 2.8.0 / CUDA 12.8.1, Container Disk 60GB.
2. Jupyter 터미널에서 이 브랜치를 받는다.
   ```bash
   cd /workspace && git clone -b exp/hypA-rl-bench https://github.com/fijitlwkr/MMDL.git && cd MMDL
   ```
3. HF 에 로그인한다(bench64 가 비공개 데이터셋). "Add token as git credential?" 에는 n.
   ```bash
   HF_HOME=/workspace/.cache/huggingface huggingface-cli login
   ```
4. 설치·데이터·모델 준비(약 15분). 끝에 `A=ok`, `B=ok` 가 나오는지 본다. B 가 '불가'면 이유가 같이 나오고, 에러 전문은 `/workspace/hypA_rl_bench/setup/` 에 있다.
   ```bash
   bash experiments/hypA-rl-bench/setup.sh 2>&1 | tee /workspace/setup.log
   ```
5. 테스트 A 다음에 B 를 이어서 돌린다. 브라우저를 닫아도 멈추지 않는다. `tail` 은 Ctrl+C 로 빠져나와도 실행은 계속된다.
   ```bash
   nohup bash -c 'python experiments/hypA-rl-bench/test_a_generate.py --bench /workspace/hypA_rl_bench/bench64 --model_dir "$(cat /workspace/hypA_rl_bench/setup/model_dir.txt)" --out /workspace/hypA_rl_bench/test_a; bash experiments/hypA-rl-bench/test_b_grpo.sh' > /workspace/hypA_rl_bench/run.log 2>&1 &
   tail -f /workspace/hypA_rl_bench/run.log
   ```
   B 가 '불가'면 A 만 돌린다(위 명령에서 `; bash experiments/...` 부분을 뺀다).
6. 끝나면(로그 끝에 `=== swift rlhf exit ...` 와 정리 결과) 결과를 묶어서 Jupyter 파일 목록에서 내려받는다. 모델·데이터·LoRA 가중치는 뺀다.
   ```bash
   tar czf /workspace/hypA_rl_bench_results.tar.gz -C /workspace --exclude='bench64*' --exclude='*.safetensors' hypA_rl_bench
   ```
7. 내려받은 것을 확인하고 파드를 Terminate 한다.

## 결과 파일 (`/workspace/hypA_rl_bench/`)

| 경로 | 내용 |
|---|---|
| `setup/STATUS`, `setup/*.log`, `setup/06_imports.json` | 설치·pip check(swift 전/후)·import 결과 전문, 패키지 버전 |
| `test_a/REPORT.md`, `test_a/summary.json` | 테스트 A 측정 결과 |
| `test_a/responses.jsonl` | 테스트 A 응답 512줄(원문, 토큰 수, 잘림 여부, 뽑은 답, 정답 여부) |
| `test_b/b_summary.json` | 테스트 B 측정 결과(스텝별 시간·보상, 최대 VRAM, overlong, 프롬프트 비교) |
| `test_b/b_run.log` | swift 실행 로그 전체(실패하면 에러 전문이 여기 있다) |
| `test_b/prompt_dump.json`, `test_b/prompt_check.json` | 첫 롤아웃 프롬프트 덤프와 평가 입력 비교 |
| `test_b/rewards.jsonl`, `test_b/overlong.jsonl`, `test_b/vram.csv` | 보상·잘린 응답·VRAM(1초 간격) 기록 |
| `test_b/swift/**/completions.jsonl`, `logging.jsonl` | swift 가 남긴 생성 결과·스텝 로그 |

## GRPO 문제풀 사전 선별 생성 (2026-11-10 하경님 요청)

원본 모델로 후보 문항을 여러 번 풀어 응답만 저장한다. 채점은 데이터 쪽에서 한다. 생성 방식은 테스트 A 와 같다(`code/config.yaml` 그대로, 요청마다 seed 다름).

| 입력 (`MMDL-team4/hypA-rl-data` 의 `screen_v1/`) | 횟수 | 응답 | seed_offset | 출력 폴더 |
|---|---|---|---|---|
| `screen_batch1.jsonl` 앞 20문항 (형식 확인용) | 8 | 160 | 0 | `first20/` |
| `screen_batch1.jsonl` 2,200문항 | 8 | 17,600 | 0 | `batch1/` |
| `screen_heldout.jsonl` 200문항 | 4 | 800 | 100000 | `heldout/` |

seed = 3407 + seed_offset + 문항 순번(파일 안 0부터) × 횟수 + rep. 그래서 `first20` 의 seed 는 `batch1` 앞 20문항과 같고, heldout 은 batch1 과 겹치지 않는다. 문항을 256개씩 나눠 생성하며, 끊기면 같은 명령을 다시 실행하면 이어서 돈다.

출력 폴더마다 `responses.jsonl`(id, rep, seed, raw_text = 응답 전문, finish_reason, output_tokens …), `sampling_params.json`(실제 적용된 생성 설정), `run_info.json`(시간·토큰·잘림 수)이 생긴다.

1. 파드: 위 "순서" 1~4 와 같다(HF 토큰은 업로드를 하므로 **Write** 권한). `huggingface-cli` 가 없다고 나오면 로그인 전에 `pip install -q huggingface-hub==0.35.3 hf-transfer==0.1.9`.
2. 입력 받기·검사.
   ```bash
   export HF_HOME=/workspace/.cache/huggingface
   hf download MMDL-team4/hypA-rl-data --repo-type dataset --include "screen_v1/*" --local-dir /workspace/screen
   cd /workspace/screen/screen_v1 && sha256sum -c --quiet SHA256SUMS && echo SHA_OK; cd /workspace/MMDL
   ```
3. 앞 20문항 시험(약 5분) → 올리고 형식 확인받기.
   ```bash
   python experiments/hypA-rl-bench/test_a_generate.py --input /workspace/screen/screen_v1/screen_batch1.jsonl --limit 20 --n 8 --model_dir "$(cat /workspace/hypA_rl_bench/setup/model_dir.txt)" --out /workspace/screen_out/first20
   HF_HOME=/workspace/.cache/huggingface hf upload MMDL-team4/hypA-rl-data /workspace/screen_out/first20/responses.jsonl screen_v1_out/first20/responses.jsonl --repo-type dataset --commit-message "screen_v1 first20 responses"
   ```
4. 본 실행(약 2시간). 브라우저를 닫아도 멈추지 않는다.
   ```bash
   nohup bash -c 'M="$(cat /workspace/hypA_rl_bench/setup/model_dir.txt)"; D=/workspace/screen/screen_v1; O=/workspace/screen_out; python experiments/hypA-rl-bench/test_a_generate.py --input $D/screen_batch1.jsonl --n 8 --model_dir "$M" --out $O/batch1 && python experiments/hypA-rl-bench/test_a_generate.py --input $D/screen_heldout.jsonl --n 4 --seed_offset 100000 --model_dir "$M" --out $O/heldout' > /workspace/screen_out/run.log 2>&1 &
   tail -f /workspace/screen_out/run.log
   ```
5. 올리기. 두 `sampling_params.json` 은 같아야 한다(`SAME`).
   ```bash
   O=/workspace/screen_out; U=/workspace/screen_upload; cmp $O/batch1/sampling_params.json $O/heldout/sampling_params.json && echo SAME
   mkdir -p $U/batch1 $U/heldout && cp $O/batch1/responses.jsonl $U/batch1/ && cp $O/heldout/responses.jsonl $U/heldout/ && cp $O/batch1/sampling_params.json $U/
   HF_HOME=/workspace/.cache/huggingface hf upload MMDL-team4/hypA-rl-data $U screen_v1_out --repo-type dataset --commit-message "screen_v1 batch1/heldout responses"
   ```

## 정해서 한 것

- **패키지 두 가지 조정**(2026-11-08 첫 실행에서 발견). 하경님이 정한 vllm 0.11.0 / torch 2.8.0 / transformers 4.57.1 / ms-swift 4.6.0 은 그대로다.
  - datasets 4.0.0(팀 고정) → **4.8.4**: swift 4.6.0 의 데이터 전처리가 datasets 4.7.0 부터 있는 `datasets.features.Json` 을 써서, 4.0.0 에서는 학습이 데이터 로드에서 멈췄다(`ImportError: cannot import name 'Json'`).
  - **`VLLM_PLUGINS=""`**: swift 가 vLLM 에 자동 등록하는 플러그인(`swift_uembed`)이 vllm 0.11.0 에 없는 `vllm.model_executor.models.qwen3_5` 를 불러 vLLM 이 시작하지 못했다(`ModuleNotFoundError`). Qwen3-VL 에는 필요 없는 플러그인이라 A·B 모두 끄고 돌린다.
- **B 의 16문항**: bench64 에서 고정 16문항(OMR 8 + Honey 8: TQA 객관식 4, ChartQA 2, TallyQA 2)을 seed 3407 로 뽑아 매 스텝 같은 16문항을 쓴다. 스텝당 16 × 8 = 128개 생성(마이크로배치 4 × 누적 32, 4090 이면 2 × 64).
- **A 의 정답 판정**: judge 없이 규칙만 쓴다. 객관식은 팀 규칙(Qwen 파서 + Final Answer)을 먼저 쓰고, 못 뽑거나 둘이 다르면 답 끝부분의 `answer is X` → `\boxed{X}` → `**X.` 순으로 찾는다. 이 방식은 E0 seed 42 객관식 847문항에서 정오 판정이 팀 공식 채점(judge 포함)과 96.1% 같았다(끝까지 쓴 답만 보면 99.7%, 나머지는 잘린 답). 주관식은 최종 답 부분(같은 줄의 마지막 `Answer:` 뒤, 없으면 첫 줄 + 마지막 줄)에 정답이 있는지 단순 비교한다(정답 끝 마침표 제거, 숫자는 쉼표·$ 무시, 영어 숫자 단어 포함). 처음 쓴 MMMU 주관식 규칙(`eval_open`)은 bench64 정답 끝 마침표(`Sweden.`)와 이 데이터의 답 형식 때문에 맞은 답을 오답 처리해서 바꿨다. 바꾼 규칙은 주관식 응답 128개를 직접 읽은 판정과 128개 모두 같았다. 생성을 다시 하지 않고 `--regrade` 로 저장된 응답만 다시 채점한다.
- **A 의 소스별 시간**: 소스마다 256요청을 따로 한 번에 넣어 잰다. 두 소스를 섞어 넣으면 소스별 시간을 나눌 수 없다.
- **B 의 임시 보상**: 객관식은 정답 글자가 단독 대문자로 응답에 나오면 1점, 주관식은 정답 문자열(끝 마침표 제거, 대소문자 무시)이 응답에 들어 있으면 1점.
- **B 의 생성 설정**: temp 0.7 / top_p 0.8 / top_k 20 은 평가와 같게 줬다. **presence_penalty 는 swift GRPO 가 vLLM 에 넘기지 않아 0 이다**(평가는 1.5). 실제 값은 `prompt_dump.json` 의 `sampling_params` 에 찍힌다.
- **B 의 학습 설정**(요청에 없던 값, swift 일반값): lora_alpha 32, lr 1e-5, beta 0.04(swift GRPO 기본), loss_type grpo(기본), gradient checkpointing.
