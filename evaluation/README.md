# TeleAntiFraud Evaluation Utilities

This folder contains the lightweight evaluation utilities used to score
TeleAntiFraud model outputs and reasoning traces.

It is intentionally limited to evaluation and LM-as-judge scoring. Training,
ablation launchers, private API proxies, raw result files, audio files, and API
keys are not included.

## What Is Evaluated

TeleAntiFraud uses three task families:

1. **Scene classification**
   - label set: `订餐服务`, `咨询客服`, `预约服务`, `交通咨询`, `日常购物`, `打车服务`, `外卖服务`
   - expected model answer: JSON with `scene`, `reason`, `confidence`
2. **Fraud detection**
   - label set: `fraud`, `normal`
   - expected model answer: JSON with `reason`, `confidence`, `is_fraud`
3. **Fraud type classification**
   - label set: `投资诈骗`, `钓鱼诈骗`, `身份盗窃`, `彩票诈骗`, `银行诈骗`, `绑架诈骗`, `客服诈骗`, `邮件诈骗`
   - expected model answer: JSON with `fraud_type`, `reason`, `confidence`

For classification metrics we report accuracy, precision, recall, weighted F1,
micro F1, macro F1, and optional per-class scores. Use the label extracted from
the JSON answer as the prediction.

## LM-as-Judge Reasoning Score

The judge measures the quality of a model's reasoning process against a
reference answer and reference reasoning. The scoring rubric is in
`judge_prompt.txt`.

The judge rubric has three 5-point dimensions:

- logical rigor
- practical value
- expression quality

The judge is asked to estimate probabilities for each sub-score and compute the
expected score. This keeps partial credit explicit and makes the score more
diagnostic than a single preference label.

## Data Format

`prepare_judge_inputs.py` writes JSONL records like:

```json
{
  "task_type": "场景分类",
  "prompt": "...",
  "reasoning_process": "...",
  "model_answer": "...",
  "reference_answer": "...",
  "reference_reasoning": "...",
  "answer": "预约服务",
  "prediction": "..."
}
```

`run_lm_judge.py` reads that JSONL and appends judge fields.

## Prepare Judge Inputs

If your model output already has the fields above, skip this step.

For output files that contain raw model responses with `<think>` and `<answer>`
tags:

```bash
python prepare_judge_inputs.py \
  --predictions predictions.jsonl \
  --references references.json \
  --output results_forreason.jsonl
```

The reference JSON is expected to be a list of samples. Each sample should
contain `prompt`, `response`, `reasoning`, and `answer`.

## Run LM Judge

`run_lm_judge.py` uses an OpenAI-compatible Chat Completions endpoint.

```bash
export OPENAI_API_KEY="your_api_key"
# Optional; use for non-OpenAI-compatible gateways.
export OPENAI_BASE_URL="https://api.example.com/v1"

python run_lm_judge.py \
  --input results_forreason.jsonl \
  --output judged_results.jsonl \
  --model your-judge-model \
  --prompt-template judge_prompt.txt \
  --concurrency 8
```

The output keeps the original record and adds:

- `judge_response`
- `judge_model`
- `judge_error`

## Notes

- Do not include private API keys in config files. Use environment variables.
- Keep benchmark result files out of this folder unless they are small examples.
- For reproducible papers, report the judge model name, endpoint family,
  prompt template commit, decoding parameters, and number of judged samples.
