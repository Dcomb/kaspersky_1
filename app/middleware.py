"""Authentication and privacy-safe per-request audit logging for vLLM."""

import hmac
import logging
import os
import time

from starlette.responses import JSONResponse

audit = logging.getLogger("inference.audit")
audit.setLevel(logging.INFO)
if not audit.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    audit.addHandler(handler)
audit.propagate = False


async def audit_and_auth(request, call_next):
    start = time.monotonic()
    route = request.url.path
    safe_routes = {
        "/health", "/v1/models", "/v1/chat/completions",
        "/v1/completions", "/v1/responses", "/v1/embeddings",
        "/metrics", "/invocations",
    }
    logged_route = route if route in safe_routes else "other"
    status = 500
    try:
        if route != "/health":
            expected = os.environ.get("VLLM_API_KEY", "")
            supplied = request.headers.get("authorization", "")
            valid = (
                bool(expected)
                and supplied.startswith("Bearer ")
                and hmac.compare_digest(supplied[7:], expected)
            )
            if not valid:
                status = 401
                return JSONResponse({"error": "Unauthorized"}, status_code=status)
        response = await call_next(request)
        status = response.status_code
        return response
    finally:
        audit.info(
            "method=%s path=%s status=%d duration_ms=%d",
            request.method,
            logged_route,
            status,
            round((time.monotonic() - start) * 1000),
        )
