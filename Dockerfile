FROM pytorch/pytorch:2.6.0-cuda12.6-cudnn9-runtime

ENV DEBIAN_FRONTEND=noninteractive
ENV LANG=C.UTF-8
ENV LC_ALL=C.UTF-8
ENV PYTHONUNBUFFERED=1

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

RUN python -c "import nltk; nltk.download('punkt', quiet=True, download_dir='/opt/nltk_data'); nltk.download('punkt_tab', quiet=True, download_dir='/opt/nltk_data')"
ENV NLTK_DATA=/opt/nltk_data

ENV PYTHONPATH=/app
EXPOSE 7777

CMD ["python", "-m", "ebook2m4b.web_ui.app"]
