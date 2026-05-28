#!/bin/bash
# =============================================================================
# Build Dexter HMS ARM64 Docker image and push to AWS ECR
#
# Usage:
#   ./docker/build.sh <version> <ecr-url>
#
# Examples:
#   ./docker/build.sh v1.0.0 123456789.dkr.ecr.ap-south-1.amazonaws.com
#   ./docker/build.sh latest   (local build only, no push)
# =============================================================================

set -e

VERSION=${1:-latest}
ECR_URL=${2:-}
IMAGE_NAME="dexter-edge:${VERSION}"

# Ensure buildx builder with ARM64 support exists
docker buildx inspect dexter-builder > /dev/null 2>&1 || \
    docker buildx create --name dexter-builder --use

if [ -n "$ECR_URL" ]; then
    FULL_IMAGE="${ECR_URL}/${IMAGE_NAME}"
    echo "Building and pushing: ${FULL_IMAGE}"
    docker buildx build \
        --platform linux/arm64 \
        -t "${FULL_IMAGE}" \
        --push .
    echo "Done: ${FULL_IMAGE}"
else
    echo "Building locally (no ECR URL given): ${IMAGE_NAME}"
    docker buildx build \
        --platform linux/arm64 \
        -t "${IMAGE_NAME}" \
        --load .
    echo "Done: ${IMAGE_NAME}"
fi