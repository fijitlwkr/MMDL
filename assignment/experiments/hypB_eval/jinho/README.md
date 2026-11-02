# Hypothesis B Đánh Giá Mô Hình (MMMU Evaluation) — Jinho

Thư mục này chứa toàn bộ script và quy trình đánh giá chuẩn mực cho hai mô hình **E1** (Structured Reasoning) và **E2** (Direct Final Answer) sau khi hoàn tất huấn luyện.

---

## 📌 Tổng quan quy trình đánh giá

Toàn bộ quy trình chia làm 4 giai đoạn chính:

1. **Giai đoạn 1: Chuẩn bị mô hình (Merge weights)**
   - Nạp LoRA adapter từ checkpoint vừa train (hoặc từ Hugging Face nhánh `run-jinho`) và merge vào mô hình gốc `Qwen/Qwen3-VL-4B-Instruct` (bf16).
2. **Giai đoạn 2: Suy luận trên MMMU (900 câu hỏi)**
   - Chạy pipeline suy luận chính thức của repo (`code/run_generate.sh`) trên tập `MMMU validation` (900 câu hỏi thuộc 30 chuyên ngành).
   - Xuất ra file kết quả `raw.jsonl` và kiểm tra tính toàn vẹn sha256.
3. **Giai đoạn 3: Đánh giá bằng LLM Judge (OpenAI API)**
   - Chạy bộ đánh giá v2 (`code/scoring/evaluate.py`) với mô hình Judge `gpt-4.1-mini-2025-04-14` (hoặc `gpt-4o-mini`).
4. **Giai đoạn 4: Tổng hợp & so sánh (Aggregation)**
   - So sánh độ chính xác của **E1** và **E2** với mô hình baseline **M0**.

---

## 🚀 Các lệnh thực hiện nhanh

### 1. Thiết lập môi trường đánh giá:
```bash
cd /workspace/MMDL/assignment/experiments/hypB_eval/jinho
bash setup_gpu.sh
```

### 2. Chạy sinh đáp án (Inference) trên GPU:
```bash
# Chạy thử smoke test (3 câu) để kiểm tra pipeline:
bash run_gpu.sh /workspace/hypB_eval_jinho smoke

# Chạy chính thức toàn bộ 900 câu cho cả E1 và E2:
bash run_gpu.sh /workspace/hypB_eval_jinho all
```

### 3. Chấm điểm với LLM Judge:
```bash
export OPENAI_API_KEY="sk-..."
python judge_runner.py --scoring-root /workspace/hypB_eval_jinho/scoring
```

### 4. Tổng hợp và so sánh kết quả:
```bash
python aggregate.py \
  --left-raw /workspace/hypB_eval_jinho/M0/raw.jsonl --left-scores /workspace/hypB_eval_jinho/scoring/M0 \
  --right-raw /workspace/hypB_eval_jinho/E1/generation/raw.jsonl --right-scores /workspace/hypB_eval_jinho/scoring/E1 \
  --length-ids m0_length_ids.txt --k0 10 \
  --out /workspace/hypB_eval_jinho/comparison_E1_vs_M0.json
```

