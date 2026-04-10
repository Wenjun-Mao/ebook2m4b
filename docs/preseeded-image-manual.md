# Preseeded Image (Kokoro + NLTK) Manual Guide

This guide shows how to build and push an ebook2m4b image that is ready to run without runtime downloads.

Default image target used in this project:
- `ghcr.io/wenjun-mao/ebook2m4b` (single tag flow; default tag `latest`)

What gets preseeded in the image:
- NLTK tokenizers: `punkt`, `punkt_tab`
- Kokoro model snapshot: `hexgrad/Kokoro-82M` at pinned revision

## 1) Prerequisites

- Docker with BuildKit support (`docker buildx` recommended)
- Registry login for your target registry (GHCR, Docker Hub, etc.)
- Internet access during build time only
- On Windows: PowerShell 7+ (or Windows PowerShell 5.1)

## 2) Build Manually (PowerShell on Windows)

From project root in PowerShell:

```powershell
docker buildx build `
  --platform linux/amd64 `
  --build-arg KOKORO_MODEL_ID=hexgrad/Kokoro-82M `
  --build-arg KOKORO_MODEL_REVISION=f3ff3571791e39611d31c381e3a41a3af07b4987 `
  --build-arg PRESEED_KOKORO=1 `
  --tag ghcr.io/wenjun-mao/ebook2m4b:latest `
  --load `
  .
```

## 3) Build Manually (Bash on Linux/macOS)

From project root:

```bash
docker buildx build \
  --platform linux/amd64 \
  --build-arg KOKORO_MODEL_ID=hexgrad/Kokoro-82M \
  --build-arg KOKORO_MODEL_REVISION=f3ff3571791e39611d31c381e3a41a3af07b4987 \
  --build-arg PRESEED_KOKORO=1 \
  --tag ghcr.io/wenjun-mao/ebook2m4b:latest \
  --load \
  .
```

## 4) Verify Preseeded Contents in the Built Image

```bash
docker run --rm ghcr.io/wenjun-mao/ebook2m4b:latest \
  python - <<'PY'
import nltk
from pathlib import Path

nltk.data.find('tokenizers/punkt')
nltk.data.find('tokenizers/punkt_tab')

root = Path('/opt/huggingface/hub/models--hexgrad--Kokoro-82M/snapshots')
if not root.exists() or not any(root.iterdir()):
    raise SystemExit('Kokoro snapshot missing in image cache')

print('NLTK and Kokoro cache are present in image.')
PY
```

## 5) Push Manually

For GHCR:

```bash
echo "$GHCR_TOKEN" | docker login ghcr.io -u wenjun-mao --password-stdin
docker push ghcr.io/wenjun-mao/ebook2m4b:latest
```

PowerShell equivalent:

```powershell
$env:GHCR_TOKEN = "<your-ghcr-token>"
$env:GHCR_TOKEN | docker login ghcr.io -u wenjun-mao --password-stdin
docker push ghcr.io/wenjun-mao/ebook2m4b:latest
```

Make the package public once in GitHub Packages UI:
- Open `https://github.com/users/wenjun-mao/packages/container/package/ebook2m4b`
- Go to `Package settings` -> `Change visibility` -> `Public`
- After that, pulls do not require auth.

## 6) Run with Compose Using the Pushed Image

`compose.yaml` supports image overrides and defaults to in-image cache paths.

Set env vars before startup:

```bash
export EBOOK2M4B_IMAGE_WEB=ghcr.io/wenjun-mao/ebook2m4b
export EBOOK2M4B_IMAGE_WORKER=ghcr.io/wenjun-mao/ebook2m4b
export EBOOK2M4B_HF_HOME=/opt/huggingface
export EBOOK2M4B_TRANSFORMERS_CACHE=/opt/huggingface
export EBOOK2M4B_NLTK_DATA=/opt/nltk_data
export EBOOK2M4B_HF_HUB_OFFLINE=1
```

Then run:

```bash
docker compose pull web worker
docker compose up -d
```

PowerShell equivalent:

```powershell
$env:EBOOK2M4B_IMAGE_WEB = "ghcr.io/wenjun-mao/ebook2m4b"
$env:EBOOK2M4B_IMAGE_WORKER = "ghcr.io/wenjun-mao/ebook2m4b"
docker compose pull web worker
docker compose up -d
```

Notes:
- Avoid `--build` for pull-first deployment.
- If you intentionally want online fallback downloads, set `EBOOK2M4B_HF_HUB_OFFLINE=0`.

## 7) All-in-One Scripts

A script is provided for each shell:
- `scripts/build_push_preseeded_image.sh`
- `scripts/build_push_preseeded_image.ps1`

PowerShell example (Windows):

```powershell
$env:IMAGE_NAME = "ghcr.io/wenjun-mao/ebook2m4b"
$env:IMAGE_TAG = "latest"
$env:PUSH = "1"
.\scripts\build_push_preseeded_image.ps1
```

Bash example (Linux/macOS):

```bash
chmod +x scripts/build_push_preseeded_image.sh
IMAGE_NAME=ghcr.io/wenjun-mao/ebook2m4b \
IMAGE_TAG=latest \
PUSH=1 \
./scripts/build_push_preseeded_image.sh
```
