#!/bin/bash
# 部署前构建脚本：下载 Linux x86_64 + Python 3.10 版本的依赖到 _deps/
# 因为本地 Mac ARM 版依赖不能在 FC 的 debian11 环境跑

set -e

DEPS_DIR="_deps"

echo "==> 清理旧依赖..."
rm -rf "${DEPS_DIR}"

echo "==> 下载 Linux x86_64 / Python 3.11 版依赖（匹配 FC custom.debian12）..."
pip3 install \
  --target "${DEPS_DIR}" \
  -r requirements.txt \
  --platform manylinux2014_x86_64 \
  --python-version 3.11 \
  --only-binary=:all: \
  --implementation cp \
  --upgrade

echo "==> 完成，依赖大小：$(du -sh ${DEPS_DIR} | cut -f1)"
