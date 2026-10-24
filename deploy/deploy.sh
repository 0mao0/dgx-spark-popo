#!/usr/bin/env bash
# PoPo 一键部署：拉镜像 → 拉权重 → 打 preprocessor 配置补丁 → 起两容器 → 轮询 /health。
# 在 GB10 主机上执行；先 `cp .env.example .env` 并填写密钥与路径。
set -euo pipefail

DEPLOY_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${DEPLOY_DIR}/.env"
[ -f "$ENV_FILE" ] || { echo "缺少 $ENV_FILE（cp .env.example .env 后填写）" >&2; exit 1; }
set -a; . "$ENV_FILE"; set +a

: "${POPO_API_KEY:?POPO_API_KEY 未设置}"
: "${POPO_MODEL_DIR:?POPO_MODEL_DIR 未设置}"
IMAGE="${POPO_IMAGE:?POPO_IMAGE 未设置}"
REVISION="${POPO_WEIGHTS_REVISION:-af75342}"

echo "[1/5] 拉取镜像 ${IMAGE}"
docker pull "$IMAGE"

echo "[2/5] 权重（DreamEternal/MinerU-Popo @ ${REVISION}）"
if [ ! -f "${POPO_MODEL_DIR}/config.json" ]; then
  mkdir -p "$(dirname "$POPO_MODEL_DIR")"
  HF_HUB_DISABLE_XET=1 hf download DreamEternal/MinerU-Popo \
    --revision "$REVISION" --local-dir "$POPO_MODEL_DIR"
else
  echo "  已存在，跳过下载"
fi

echo "[3/5] preprocessor 配置补丁（图像 token 口径）"
python3 - "$POPO_MODEL_DIR" <<'PY'
import json, sys
root = sys.argv[1]
p = f"{root}/preprocessor_config.json"
cfg = json.load(open(p, encoding="utf-8"))
cfg["max_pixels"] = 1284506
cfg["min_pixels"] = 3136
with open(p, "w", encoding="utf-8") as f:
    f.write(json.dumps(cfg, ensure_ascii=False, indent=2))
print("  patched", p)
PY

echo "[4/5] 启动 compose（engine + proxy）"
docker compose -f "$DEPLOY_DIR/compose.yaml" --env-file "$ENV_FILE" up -d

echo "[5/5] 轮询 /health（引擎加载可达数分钟）"
PORT="${POPO_PROXY_PORT:-8008}"
for i in $(seq 1 180); do
  if curl -sf "http://127.0.0.1:${PORT}/health" >/dev/null; then
    echo "OK: http://127.0.0.1:${PORT}/health 200"
    echo "调用方式: POPO_CONFIGS='{\"name\":\"local\",\"url\":\"http://<host>:${PORT}/v1\",\"api_key\":\"<POPO_API_KEY>\",\"model\":\"Popo\"}'"
    exit 0
  fi
  sleep 10
done
echo "超时：健康检查 30 分钟未通过；排查: docker logs popo-engine / docker logs popo-api" >&2
exit 1
