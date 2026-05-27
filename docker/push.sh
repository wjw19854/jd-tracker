#!/bin/bash
# Docker Hub 推送脚本
# 用法: ./push.sh [版本号]
# 示例: ./push.sh          → 使用 pyproject.toml 中的版本号
#       ./push.sh 0.2.1    → 手动指定版本号
set -e

cd "$(dirname "$0")/.."

# 版本号：优先参数，其次从 pyproject.toml 读取
if [ -n "$1" ]; then
    VERSION="$1"
else
    VERSION=$(grep '^version =' pyproject.toml | head -1 | sed 's/.*"\(.*\)"/\1/')
fi

IMAGE="yourusername/jd-tracker"

echo "============================================"
echo " 构建 & 推送 jd-tracker Docker 镜像"
echo " 版本: $VERSION"
echo " 镜像: $IMAGE"
echo "============================================"

# 构建
echo "[1/3] 构建镜像..."
docker build -t "$IMAGE:latest" -t "$IMAGE:$VERSION" -f docker/Dockerfile .

# 推送
echo "[2/3] 推送 latest..."
docker push "$IMAGE:latest"

echo "[3/3] 推送 $VERSION..."
docker push "$IMAGE:$VERSION"

echo ""
echo "✅ 完成: $IMAGE:latest / $IMAGE:$VERSION"
echo ""
echo "服务器端拉取: docker pull $IMAGE:$VERSION"
