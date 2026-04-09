#!/usr/bin/env python3
"""Prepare TeleAntiFraud model outputs for LM-as-judge scoring."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


THINK_RE = re.compile(r"<think>(.*?)</think>", re.DOTALL)
ANSWER_RE = re.compile(r"<answer>(.*?)</answer>", re.DOTALL)


def read_json_or_jsonl(path: Path) -> list[dict[str, Any]]:
    if path.suffix == ".jsonl":
        records = []
        with path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    records.append(json.loads(line))
        return records

    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and isinstance(data.get("results"), list):
        return data["results"]
    raise ValueError(f"Unsupported JSON structure in {path}")


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")


def extract_tagged_response(text: str) -> tuple[str | None, str | None]:
    think_match = THINK_RE.search(text)
    answer_match = ANSWER_RE.search(text)
    reasoning = think_match.group(1).strip() if think_match else None
    answer = answer_match.group(1).strip() if answer_match else text.strip()
    return reasoning, answer


def normalize_prompt(prompt: Any) -> str:
    """Create a stable string key for nested chat prompts."""
    return json.dumps(prompt, ensure_ascii=False, sort_keys=True)


def infer_task_type(prompt_or_text: Any) -> str:
    text = json.dumps(prompt_or_text, ensure_ascii=False)
    if "fraud_type" in text:
        return "欺诈类型分类"
    if "is_fraud" in text:
        return "欺诈分类"
    if "scene" in text:
        return "场景分类"
    return "未知"


def prediction_prompt(record: dict[str, Any]) -> Any:
    return record.get("talk_list") or record.get("prompt") or record.get("messages")


def prediction_text(record: dict[str, Any]) -> str:
    for key in ("messages", "prediction", "model_answer", "response", "text"):
        value = record.get(key)
        if isinstance(value, str):
            return value
    raise ValueError("Prediction record does not contain a text response")


def reference_index(references: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    index = {}
    for item in references:
        if "prompt" not in item:
            continue
        index[normalize_prompt(item["prompt"])] = item
    return index


def convert(predictions: list[dict[str, Any]], references: list[dict[str, Any]]) -> list[dict[str, Any]]:
    refs = reference_index(references)
    converted = []
    missing = 0

    for pred in predictions:
        prompt = prediction_prompt(pred)
        ref = refs.get(normalize_prompt(prompt))
        if ref is None:
            missing += 1
            continue

        raw_prediction = prediction_text(pred)
        reasoning, model_answer = extract_tagged_response(raw_prediction)
        if reasoning is None:
            reasoning = pred.get("reasoning") or pred.get("reasoning_process") or ""

        converted.append(
            {
                "task_type": infer_task_type(prompt),
                "prompt": prompt,
                "reasoning_process": reasoning,
                "model_answer": model_answer,
                "reference_answer": ref.get("response", ""),
                "reference_reasoning": ref.get("reasoning", ""),
                "answer": ref.get("answer", ""),
                "prediction": raw_prediction,
            }
        )

    if missing:
        print(f"Skipped {missing} predictions because no exact reference prompt matched.")
    return converted


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--references", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    predictions = read_json_or_jsonl(args.predictions)
    references = read_json_or_jsonl(args.references)
    converted = convert(predictions, references)
    write_jsonl(args.output, converted)
    print(f"Wrote {len(converted)} judge-input records to {args.output}")


if __name__ == "__main__":
    main()
