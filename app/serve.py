"""Translate ConfigMap environment values into an explicit vLLM command."""

import os
from pathlib import Path


def setting(name, default):
    return os.environ.get(name, default)


def main():
    revision = setting("HF_REVISION", "")
    if len(revision) != 40 or not all(c in "0123456789abcdef" for c in revision):
        raise SystemExit("HF_REVISION must be a full 40-character commit SHA")
    model_dir = Path("/models") / revision
    marker = model_dir / ".ready"
    model_id = setting("HF_MODEL_ID", "Qwen/Qwen2.5-0.5B-Instruct")
    if not marker.is_file() or marker.read_text().strip() != f"{model_id}@{revision}":
        raise SystemExit(f"Model snapshot is not ready: {model_dir}")
    if not os.environ.get("VLLM_API_KEY"):
        raise SystemExit("VLLM_API_KEY is required")
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    args = [
        "vllm", "serve", str(model_dir),
        "--host", "0.0.0.0", "--port", "8000",
        "--served-model-name", model_id,
        "--dtype", setting("VLLM_DTYPE", "bfloat16"),
        "--max-model-len", setting("VLLM_MAX_MODEL_LEN", "1024"),
        "--max-num-seqs", setting("VLLM_MAX_NUM_SEQS", "1"),
        "--max-num-batched-tokens", setting("VLLM_MAX_NUM_BATCHED_TOKENS", "1024"),
        "--middleware", "app.middleware.audit_and_auth",
        "--no-enable-log-requests", "--no-enable-log-outputs",
        "--disable-uvicorn-access-log",
        "--uvicorn-log-level", "warning",
    ]
    for name in (
        "VLLM_DTYPE", "VLLM_MAX_MODEL_LEN", "VLLM_MAX_NUM_SEQS",
        "VLLM_MAX_NUM_BATCHED_TOKENS",
    ):
        os.environ.pop(name, None)
    os.execvp(args[0], args)


if __name__ == "__main__":
    main()
