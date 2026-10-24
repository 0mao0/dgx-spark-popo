#!/usr/bin/env bash
# 对比 pin 的上游 SHA 与 opendatalab/MinerU-Popo master，列出新提交。
# 用法: scripts/check_upstream.sh   （依赖 curl；API 匿名限额 60 次/小时）
set -euo pipefail

PINNED="8b9a8bd57ef3c785b45d7ed696fdadfbe7184992"   # 本仓 pin 的上游提交
UPSTREAM="opendatalab/MinerU-Popo"

json=$(curl -fsSL "https://api.github.com/repos/${UPSTREAM}/compare/${PINNED}...master")
ahead=$(printf '%s' "$json" | grep -o '"ahead_by": *[0-9]*' | head -1 | grep -o '[0-9]*$')

if [ "${ahead:-0}" = "0" ]; then
  echo "上游无新提交（pin ${PINNED:0:7}）"
  exit 0
fi

echo "上游领先 ${ahead} 个提交："
printf '%s' "$json" | grep -o '"message": *"[^"]*"' | sed 's/"message": *"//; s/"$//' | head -n "$ahead"
echo
echo "同步步骤：rebase 上游 -> 重生成补丁 -> 更新本文件 PINNED -> 10 本差分 -> 发 tag"
