import json
import os
from urllib.error import HTTPError
from urllib.request import Request, urlopen


def call(token):
    headers = {"Content-Type": "application/json"}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    payload = {
        "model": os.environ.get("HF_MODEL_ID", "Qwen/Qwen2.5-0.5B-Instruct"),
        "messages": [{"role": "user", "content": "Reply with one short greeting."}],
        "max_tokens": 16,
        "temperature": 0,
    }
    url = os.environ.get("API_URL", "http://localhost:8000").rstrip("/")
    request = Request(
        f"{url}/v1/chat/completions",
        data=json.dumps(payload).encode(),
        headers=headers,
    )
    try:
        with urlopen(request, timeout=180) as response:
            return response.status, json.load(response)
    except HTTPError as error:
        return error.code, json.load(error)


def main():
    token = os.environ["API_TOKEN"]
    unauthorized_status, _ = call(None)
    assert unauthorized_status == 401, f"Expected 401 without token, got {unauthorized_status}"
    status, result = call(token)
    assert status == 200, f"Expected 200 {status}: {result}"
    text = result["choices"][0]["message"]["content"]
    assert text, "Empty model response"
    print("Authorization and inference: OK")


if __name__ == "__main__":
    main()
