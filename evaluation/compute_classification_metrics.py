#!/usr/bin/env python3
"""Compute TeleAntiFraud classification metrics from prediction JSON/JSONL."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any


FRAUD_TYPES = ["投资诈骗", "钓鱼诈骗", "身份盗窃", "彩票诈骗", "银行诈骗", "绑架诈骗", "客服诈骗", "邮件诈骗"]
SCENE_TYPES = ["订餐服务", "咨询客服", "预约服务", "交通咨询", "日常购物", "打车服务", "外卖服务"]


def read_json_or_jsonl(path: Path) -> list[dict[str, Any]]:
    if path.suffix == ".jsonl":
        rows = []
        with path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
        return rows
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and isinstance(data.get("results"), list):
        return data["results"]
    if isinstance(data, dict) and isinstance(data.get("results"), dict):
        flattened = []
        for value in data["results"].values():
            if isinstance(value, list):
                flattened.extend(value)
        return flattened
    raise ValueError(f"Unsupported data structure in {path}")


def extract_json_object(text: str) -> dict[str, Any] | None:
    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", text):
        try:
            obj, _ = decoder.raw_decode(text[match.start() :])
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            return obj
    return None


def response_text(record: dict[str, Any]) -> str:
    for key in ("model_answer", "prediction", "messages", "response", "respond_text", "final_prediction"):
        value = record.get(key)
        if isinstance(value, str):
            return value
    return json.dumps(record, ensure_ascii=False)


def label_from_record(record: dict[str, Any], task: str, label_key: str) -> str:
    if label_key in record:
        value = record[label_key]
        if isinstance(value, bool):
            return "fraud" if value else "normal"
        return str(value)

    text = response_text(record)
    parsed = extract_json_object(text) or {}

    if task == "fraud":
        value = parsed.get("is_fraud")
        if isinstance(value, bool):
            return "fraud" if value else "normal"
        if isinstance(value, str):
            return "fraud" if value.lower() == "true" else "normal"
        return "fraud" if "is_fraud" in text and "true" in text.lower() else "normal"

    if task == "fraud_type":
        value = parsed.get("fraud_type")
        if isinstance(value, str):
            return closest_closed_label(value, FRAUD_TYPES)
        return closest_closed_label(text, FRAUD_TYPES)

    if task == "scene":
        value = parsed.get("scene")
        if isinstance(value, str):
            return closest_closed_label(value, SCENE_TYPES)
        return closest_closed_label(text, SCENE_TYPES)

    raise ValueError(f"Unknown task: {task}")


def closest_closed_label(text: str, labels: list[str]) -> str:
    for label in labels:
        if label == text or label in text:
            return label
    return "unknown"


def safe_div(num: float, den: float) -> float:
    return num / den if den else 0.0


def binary_or_per_class_metrics(y_true: list[str], y_pred: list[str]) -> dict[str, Any]:
    labels = sorted(set(y_true) | set(y_pred))
    per_class = {}
    total = len(y_true)
    correct = sum(t == p for t, p in zip(y_true, y_pred))

    weighted_f1_num = 0.0
    macro_f1_num = 0.0
    for label in labels:
        tp = sum(t == label and p == label for t, p in zip(y_true, y_pred))
        fp = sum(t != label and p == label for t, p in zip(y_true, y_pred))
        fn = sum(t == label and p != label for t, p in zip(y_true, y_pred))
        support = sum(t == label for t in y_true)
        precision = safe_div(tp, tp + fp)
        recall = safe_div(tp, tp + fn)
        f1 = safe_div(2 * precision * recall, precision + recall)
        per_class[label] = {
            "precision": precision,
            "recall": recall,
            "f1_score": f1,
            "support": support,
        }
        weighted_f1_num += f1 * support
        macro_f1_num += f1

    return {
        "accuracy": safe_div(correct, total),
        "weighted_f1": safe_div(weighted_f1_num, total),
        "micro_f1": safe_div(correct, total),
        "macro_f1": safe_div(macro_f1_num, len(labels)),
        "per_class_metrics": per_class,
        "label_distribution": {
            "ground_truth": dict(Counter(y_true)),
            "prediction": dict(Counter(y_pred)),
        },
        "sample_count": total,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--task", choices=["scene", "fraud", "fraud_type"], required=True)
    parser.add_argument("--label-key", default="answer", help="Ground-truth label field in each record.")
    parser.add_argument("--prediction-key", default="prediction_label", help="Optional parsed prediction label field.")
    args = parser.parse_args()

    records = read_json_or_jsonl(args.input)
    y_true = [label_from_record(record, args.task, args.label_key) for record in records]
    y_pred = [label_from_record(record, args.task, args.prediction_key) for record in records]
    metrics = binary_or_per_class_metrics(y_true, y_pred)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as f:
        json.dump(metrics, f, ensure_ascii=False, indent=2)
    print(f"Wrote metrics for {len(records)} samples to {args.output}")


if __name__ == "__main__":
    main()
