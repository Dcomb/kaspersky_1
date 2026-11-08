FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/opt/service \
    HF_HOME=/tmp/huggingface \
    XDG_CACHE_HOME=/tmp/cache \
    TORCH_HOME=/tmp/torch \
    VLLM_NO_USAGE_STATS=1

RUN apt-get update && apt-get install -y --no-install-recommends g++ libnuma1 libgomp1 \
    && rm -rf /var/lib/apt/lists/*
RUN groupadd --gid 6767 app && useradd --uid 6767 --gid 6767 --create-home app \
    && mkdir -p /opt/service /models /tmp/huggingface \
    && chown -R app:app /opt/service /models /tmp/huggingface

WORKDIR /opt/service
COPY requirements.txt ./
RUN python -m pip install --no-cache-dir --extra-index-url https://download.pytorch.org/whl/cpu -r requirements.txt
RUN set -eu; iomp_path="$(find /usr/local/lib -name libiomp5.so -print -quit)"; \
    test -n "$iomp_path"; mkdir -p /opt/lib; ln -s "$iomp_path" /opt/lib/libiomp5.so
ENV LD_PRELOAD=/opt/lib/libiomp5.so
COPY --chown=app:app app/ ./app/

USER 6767:6767
EXPOSE 8000
CMD ["python", "-m", "app.serve"]
