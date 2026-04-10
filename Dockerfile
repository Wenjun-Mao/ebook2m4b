FROM pytorch/pytorch:2.6.0-cuda12.6-cudnn9-runtime

ARG KOKORO_MODEL_ID=hexgrad/Kokoro-82M
ARG KOKORO_MODEL_REVISION=f3ff3571791e39611d31c381e3a41a3af07b4987
ARG PRESEED_KOKORO=1

ENV DEBIAN_FRONTEND=noninteractive
ENV LANG=C.UTF-8
ENV LC_ALL=C.UTF-8
ENV PYTHONUNBUFFERED=1
ENV HF_HOME=/opt/huggingface
ENV TRANSFORMERS_CACHE=/opt/huggingface
ENV NLTK_DATA=/opt/nltk_data

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    git \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml README.md /app/
COPY ebook2m4b /app/ebook2m4b
RUN --mount=type=cache,target=/root/.cache/uv \
    pip install --no-cache-dir --upgrade pip uv && \
    uv pip install --system /app

RUN mkdir -p "${HF_HOME}" "${NLTK_DATA}" && \
    KOKORO_MODEL_ID="${KOKORO_MODEL_ID}" \
    KOKORO_MODEL_REVISION="${KOKORO_MODEL_REVISION}" \
    PRESEED_KOKORO="${PRESEED_KOKORO}" \
    python - <<'PY'
import os

import nltk

nltk.download("punkt", quiet=True, download_dir="/opt/nltk_data")
nltk.download("punkt_tab", quiet=True, download_dir="/opt/nltk_data")

if os.environ.get("PRESEED_KOKORO", "1") == "1":
    from huggingface_hub import snapshot_download

    snapshot_download(
        repo_id=os.environ["KOKORO_MODEL_ID"],
        revision=os.environ.get("KOKORO_MODEL_REVISION") or None,
        cache_dir=os.environ["HF_HOME"],
    )
PY

ENV PYTHONPATH=/app
EXPOSE 7777

CMD ["python", "-m", "ebook2m4b.web_ui.app"]
