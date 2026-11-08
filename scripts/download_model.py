import os
import re
from pathlib import Path

from huggingface_hub import snapshot_download


def main():
    model_id = os.environ["HF_MODEL_ID"]
    revision = os.environ["HF_REVISION"]
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise SystemExit("HF_REVISION must be a full 40-character commit SHA")
    model_dir = Path("/models") / revision
    marker = model_dir / ".ready"
    if marker.is_file() and marker.read_text().strip() == f"{model_id}@{revision}":
        if (model_dir / "config.json").is_file() and any(model_dir.glob("*.safetensors")):
            print("Pinned model snapshot already present on PVC; skipping Hugging Face")
            return

    model_dir.mkdir(parents=True, exist_ok=True)
    marker.unlink(missing_ok=True)
    token = os.environ.get("HF_TOKEN") or None
    snapshot_download(repo_id=model_id, revision=revision, local_dir=model_dir, token=token)
    if not (model_dir / "config.json").is_file() or not any(model_dir.glob("*.safetensors")):
        raise SystemExit("Downloaded snapshot is incomplete")
    temporary = model_dir / ".ready.tmp"
    temporary.write_text(f"{model_id}@{revision}\n")
    temporary.replace(marker)
    print("Pinned model snapshot ready on PVC")


if __name__ == "__main__":
    main()
