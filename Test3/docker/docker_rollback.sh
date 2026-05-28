#!/bin/bash
# Roll back the dexter-edge image to a specific ECR tag and restart the stack.
#
# Usage:
#   docker_rollback.sh sha-abc1234     # roll back to a specific commit build
#   docker_rollback.sh v1.2.3          # roll back to a semver release
#
# To list recent available tags:
#   docker_rollback.sh --list
set -euo pipefail

ECR_REGISTRY="901178127457.dkr.ecr.ap-south-1.amazonaws.com"
ECR_REPO="dexter-edge"
REGION="${AWS_REGION:-ap-south-1}"
COMPOSE_DIR="/home/pi/Test3"

ecr_login() {
  aws ecr get-login-password --region "$REGION" \
    | docker login --username AWS --password-stdin "$ECR_REGISTRY"
}

if [[ "${1:-}" == "--list" ]]; then
  ecr_login
  echo "Recent dexter-edge tags in ECR:"
  aws ecr describe-images \
    --repository-name "$ECR_REPO" \
    --region "$REGION" \
    --query 'sort_by(imageDetails,&imagePushedAt)[-15:].imageTags[]' \
    --output text | tr '\t' '\n' | grep -v buildcache | grep -v "^latest$" | sort
  exit 0
fi

TAG="${1:-}"
if [[ -z "$TAG" ]]; then
  echo "Usage: $0 <tag>        (e.g. sha-abc1234)"
  echo "       $0 --list       (show recent tags)"
  exit 1
fi

IMAGE="${ECR_REGISTRY}/${ECR_REPO}:${TAG}"
LATEST="${ECR_REGISTRY}/${ECR_REPO}:latest"

echo "==> Authenticating to ECR..."
ecr_login

echo "==> Pulling ${IMAGE}..."
docker pull "$IMAGE"

echo "==> Re-tagging as :latest..."
docker tag "$IMAGE" "$LATEST"

echo "==> Restarting stack..."
cd "$COMPOSE_DIR"
docker compose up -d --remove-orphans

echo ""
echo "Rollback to ${TAG} complete."
echo "Run 'docker compose ps' to verify container states."