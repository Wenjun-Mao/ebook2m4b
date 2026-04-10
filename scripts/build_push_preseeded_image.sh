#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"

REQUIRED_TOOLS=(docker)
MISSING_TOOLS=()
for tool in "${REQUIRED_TOOLS[@]}"; do
  command -v "${tool}" >/dev/null 2>&1 || MISSING_TOOLS+=("${tool}")
done

if [[ "${#MISSING_TOOLS[@]}" -gt 0 ]]; then
  echo "Error: missing required tools: ${MISSING_TOOLS[*]}" >&2
  echo "Install Docker Desktop or Docker Engine, then re-run this script." >&2
  exit 1
fi

IMAGE_NAME="${IMAGE_NAME:-ghcr.io/wenjun-mao/ebook2m4b}"
IMAGE_TAG="${IMAGE_TAG:-latest}"
PUSH="${PUSH:-1}"
PLATFORM="${PLATFORM:-linux/amd64}"
DOCKERFILE_PATH="${DOCKERFILE_PATH:-${REPO_ROOT}/Dockerfile}"

KOKORO_MODEL_ID="${KOKORO_MODEL_ID:-hexgrad/Kokoro-82M}"
KOKORO_MODEL_REVISION="${KOKORO_MODEL_REVISION:-f3ff3571791e39611d31c381e3a41a3af07b4987}"
PRESEED_KOKORO="${PRESEED_KOKORO:-1}"

if [[ ! -f "${DOCKERFILE_PATH}" ]]; then
  echo "Error: Dockerfile not found at ${DOCKERFILE_PATH}" >&2
  exit 1
fi

if [[ "${IMAGE_NAME}" == ghcr.io/* ]] && [[ -n "${GHCR_TOKEN:-}" ]]; then
  GHCR_USERNAME="${GHCR_USERNAME:-${IMAGE_NAME#ghcr.io/}}"
  GHCR_USERNAME="${GHCR_USERNAME%%/*}"
  echo "Logging in to ghcr.io as ${GHCR_USERNAME} ..."
  printf '%s' "${GHCR_TOKEN}" | docker login ghcr.io -u "${GHCR_USERNAME}" --password-stdin
fi

TAGS=("${IMAGE_NAME}:${IMAGE_TAG}")

echo "Building preseeded image with:"
echo "  Image: ${IMAGE_NAME}"
echo "  Tag: ${IMAGE_TAG}"
echo "  Platform: ${PLATFORM}"
echo "  Kokoro model: ${KOKORO_MODEL_ID}@${KOKORO_MODEL_REVISION}"
echo "  Preseed Kokoro: ${PRESEED_KOKORO}"

BUILD_ARGS=(
  --build-arg "KOKORO_MODEL_ID=${KOKORO_MODEL_ID}"
  --build-arg "KOKORO_MODEL_REVISION=${KOKORO_MODEL_REVISION}"
  --build-arg "PRESEED_KOKORO=${PRESEED_KOKORO}"
)

TAG_ARGS=()
for tag in "${TAGS[@]}"; do
  TAG_ARGS+=(--tag "${tag}")
done

if docker buildx version >/dev/null 2>&1; then
  MODE_FLAG="--load"
  if [[ "${PUSH}" == "1" ]]; then
    MODE_FLAG="--push"
  fi

  docker buildx build \
    --platform "${PLATFORM}" \
    --file "${DOCKERFILE_PATH}" \
    "${BUILD_ARGS[@]}" \
    "${TAG_ARGS[@]}" \
    "${MODE_FLAG}" \
    "${REPO_ROOT}"
else
  docker build \
    --file "${DOCKERFILE_PATH}" \
    "${BUILD_ARGS[@]}" \
    "${TAG_ARGS[@]}" \
    "${REPO_ROOT}"

  if [[ "${PUSH}" == "1" ]]; then
    for tag in "${TAGS[@]}"; do
      docker push "${tag}"
    done
  fi
fi

echo "Done. Built image tags:"
for tag in "${TAGS[@]}"; do
  echo "  ${tag}"
done

echo
echo "Suggested runtime env (already defaulted in compose.yaml):"
echo "  EBOOK2M4B_HF_HOME=/opt/huggingface"
echo "  EBOOK2M4B_TRANSFORMERS_CACHE=/opt/huggingface"
echo "  EBOOK2M4B_NLTK_DATA=/opt/nltk_data"
echo "  EBOOK2M4B_HF_HUB_OFFLINE=1"

echo
echo "If you want to pull this image on another host, set:"
echo "  IMAGE_NAME=${IMAGE_NAME}"
echo "  IMAGE_TAG=${IMAGE_TAG}"
