import argparse
import json
import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.request import Request, urlopen


def percentile(values, p):
    ordered = sorted(values)
    index = (len(ordered) - 1) * p
    lower = int(index)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (index - lower)


def run_one(prompt, max_tokens):
    url = os.environ.get("API_URL", "http://localhost:8000").rstrip("/")
    token = os.environ["API_TOKEN"]
    model = os.environ.get("HF_MODEL_ID", "Qwen/Qwen2.5-0.5B-Instruct")
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": 0,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    request = Request(
        f"{url}/v1/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    started = time.monotonic()
    first_token = None
    usage = {}
    with urlopen(request, timeout=300) as response:
        for line in response:
            if not line.startswith(b"data: ") or line.strip() == b"data: [DONE]":
                continue
            event = json.loads(line[6:])
            usage = event.get("usage") or usage
            if first_token is None and any(
                choice.get("delta", {}).get("content") for choice in event.get("choices", [])
            ):
                first_token = time.monotonic()
    ended = time.monotonic()
    return {
        "latency": ended - started,
        "ttft": first_token - started if first_token is not None else None,
        "completion_tokens": usage.get("completion_tokens", 0),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--requests", type=int, default=6)
    parser.add_argument("--concurrency", type=int, nargs="+", default=[1, 2, 4])
    parser.add_argument("--max-tokens", type=int, default=64)
    args = parser.parse_args()
    prompts = {
        "short": "Briefly explain what a Kubernetes Pod is.",
        "long": (
            "Read this Kubernetes incident report and name the most likely cause of the "
            "failed API requests in one sentence. The team runs a small language model "
            "behind a ClusterIP Service. A Deployment contains an init container that "
            "downloads a pinned model revision to a PersistentVolumeClaim, followed by "
            "a rootless inference container that reads the same volume. The init container "
            "completed successfully and logged that the pinned model snapshot was already "
            "present, so it skipped the download. The PVC is Bound, the inference container "
            "is Running, and its readiness probe receives HTTP 200 from /health. A developer "
            "uses kubectl port-forward to reach the Service on localhost:8000. A request to "
            "/v1/chat/completions without an Authorization header receives HTTP 401 in under "
            "a second. The same request with the configured Bearer token receives HTTP 200 "
            "and a generated answer. No pod restarts or out-of-memory events are present. "
            "The application logs record only the method, route, status and duration; they "
            "do not contain the prompt or response body. Another developer claims that the "
            "401 proves the model failed to load, while a third suspects the PVC is missing. "
            "Which explanation best fits the observed 401 responses?"
        ),
    }
    run_id = uuid.uuid4().hex
    print("scenario,concurrency,success,errors,ttft_p50_s,ttft_p95_s,latency_p50_s,latency_p95_s,req_per_s,output_tok_per_s")
    for scenario, prompt in prompts.items():
        for concurrency in args.concurrency:
            successes = []
            errors = 0
            started = time.monotonic()
            with ThreadPoolExecutor(max_workers=concurrency) as pool:
                futures = [
                    pool.submit(run_one, f"Request {run_id}-{scenario}-{index}: {prompt}", args.max_tokens)
                    for index in range(args.requests)
                ]
                for future in as_completed(futures):
                    try:
                        successes.append(future.result())
                    except Exception:
                        errors += 1
            elapsed = time.monotonic() - started
            if successes:
                ttft = [item["ttft"] for item in successes if item["ttft"] is not None]
                latency = [item["latency"] for item in successes]
                row = [
                    scenario, concurrency, len(successes), errors,
                    round(percentile(ttft, .5), 3) if ttft else "NA",
                    round(percentile(ttft, .95), 3) if ttft else "NA",
                    round(percentile(latency, .5), 3),
                    round(percentile(latency, .95), 3),
                    round(len(successes) / elapsed, 3),
                    round(sum(item["completion_tokens"] for item in successes) / elapsed, 3),
                ]
            else:
                row = [scenario, concurrency, 0, errors, "NA", "NA", "NA", "NA", 0, 0]
            print(",".join(map(str, row)), flush=True)


if __name__ == "__main__":
    main()
