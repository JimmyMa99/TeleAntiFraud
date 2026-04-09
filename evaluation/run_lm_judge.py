#!/usr/bin/env python3
"""Score TeleAntiFraud reasoning traces with an OpenAI-compatible LM judge."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


DEFAULT_BASE_URL = "https://api.openai.com/v1"


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    records = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def append_jsonl(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def load_done_keys(path: Path, key_field: str) -> set[str]:
    if not path.exists():
        return set()
    done = set()
    for record in read_jsonl(path):
        key = record.get(key_field)
        if key is not None and record.get("judge_error") in (None, ""):
            done.add(str(key))
    return done


def format_prompt(template: str, record: dict[str, Any]) -> str:
    return template.format(
        reasoning_process=record.get("reasoning_process", ""),
        model_answer=record.get("model_answer", ""),
        reference_answer=record.get("reference_answer", ""),
        reference_reasoning=record.get("reference_reasoning", ""),
    )


def post_chat_completion(
    *,
    base_url: str,
    api_key: str,
    model: str,
    prompt: str,
    temperature: float,
    max_tokens: int,
    timeout: float,
) -> str:
    url = f"{base_url.rstrip('/')}/chat/completions"
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        data = json.loads(response.read().decode("utf-8"))
    return data["choices"][0]["message"]["content"]


async def judge_one(
    *,
    record: dict[str, Any],
    prompt: str,
    args: argparse.Namespace,
    api_key: str,
    semaphore: asyncio.Semaphore,
) -> dict[str, Any]:
    async with semaphore:
        for attempt in range(args.max_retries + 1):
            try:
                judge_response = await asyncio.to_thread(
                    post_chat_completion,
                    base_url=args.base_url,
                    api_key=api_key,
                    model=args.model,
                    prompt=prompt,
                    temperature=args.temperature,
                    max_tokens=args.max_tokens,
                    timeout=args.timeout,
                )
                output = dict(record)
                output.update(
                    {
                        "judge_response": judge_response,
                        "judge_model": args.model,
                        "judge_error": "",
                    }
                )
                return output
            except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, KeyError, json.JSONDecodeError) as exc:
                if attempt >= args.max_retries:
                    output = dict(record)
                    output.update(
                        {
                            "judge_response": "",
                            "judge_model": args.model,
                            "judge_error": f"{type(exc).__name__}: {exc}",
                        }
                    )
                    return output
                delay = min(args.retry_max_delay, args.retry_initial_delay * (2**attempt))
                delay += random.uniform(0, 0.25 * delay)
                await asyncio.sleep(delay)

    raise RuntimeError("unreachable")


async def run(args: argparse.Namespace) -> None:
    api_key = args.api_key or os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise SystemExit("Set OPENAI_API_KEY or pass --api-key.")

    template = args.prompt_template.read_text(encoding="utf-8")
    records = read_jsonl(args.input)

    for idx, record in enumerate(records):
        record.setdefault(args.key_field, str(idx))

    done = load_done_keys(args.output, args.key_field) if args.resume else set()
    pending = [record for record in records if str(record.get(args.key_field)) not in done]

    semaphore = asyncio.Semaphore(args.concurrency)
    tasks = [
        judge_one(
            record=record,
            prompt=format_prompt(template, record),
            args=args,
            api_key=api_key,
            semaphore=semaphore,
        )
        for record in pending
    ]

    completed = 0
    for task in asyncio.as_completed(tasks):
        output = await task
        append_jsonl(args.output, output)
        completed += 1
        if completed % args.log_every == 0 or completed == len(tasks):
            print(f"Judged {completed}/{len(tasks)} records")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--prompt-template", type=Path, default=Path("judge_prompt.txt"))
    parser.add_argument("--model", required=True)
    parser.add_argument("--base-url", default=os.environ.get("OPENAI_BASE_URL", DEFAULT_BASE_URL))
    parser.add_argument("--api-key", default=None)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--max-tokens", type=int, default=4096)
    parser.add_argument("--timeout", type=float, default=600)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--max-retries", type=int, default=5)
    parser.add_argument("--retry-initial-delay", type=float, default=5)
    parser.add_argument("--retry-max-delay", type=float, default=120)
    parser.add_argument("--key-field", default="task_id")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--log-every", type=int, default=20)
    return parser.parse_args()


def main() -> None:
    started = time.time()
    args = parse_args()
    asyncio.run(run(args))
    print(f"Finished in {time.time() - started:.1f}s")


if __name__ == "__main__":
    main()
