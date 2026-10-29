#!/usr/bin/env bash
# PoPo 一键部署：拉镜像 → 拉权重 → 打 preprocessor 配置补丁 → 起两容器 → 轮询 /health。
# 在 GB10 主机上执行；先 `cp .env.example .env` 并填写密钥与路径。
# 用法: ./deploy.sh [--start|--no-start]；--no-start 只做准备工作（镜像/权重/补丁）。
set -euo pipefail

usage() {
  cat <<'EOF'
用法: deploy.sh [--start|--no-start] [-h|--help]
  --start      拉镜像/权重、打补丁后启动容器并轮询 /health（默认）
  --no-start   只做准备工作（拉镜像、拉权重、打配置补丁），不启动容器、不轮询健康
EOF
}

START=1
for arg in "$@"; do
  case "$arg" in
    --start) START=1 ;;
    --no-start) START=0 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "未知参数: $arg" >&2; usage >&2; exit 2 ;;
  esac
done

DEPLOY_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${DEPLOY_DIR}/.env"
[ -f "$ENV_FILE" ] || { echo "缺少 $ENV_FILE（cp .env.example .env 后填写）" >&2; exit 1; }
set -a; . "$ENV_FILE"; set +a

: "${POPO_API_KEY:?POPO_API_KEY 未设置}"
: "${POPO_MODEL_DIR:?POPO_MODEL_DIR 未设置}"
IMAGE="${POPO_IMAGE:?POPO_IMAGE 未设置}"
REVISION="${POPO_WEIGHTS_REVISION:-af75342}"
export HF_ENDPOINT="${POPO_HF_ENDPOINT:-https://hf-mirror.com}"
USE_MODELSCOPE="${POPO_USE_MODELSCOPE:-0}"

echo "[1/5] 拉取镜像 ${IMAGE}"
docker pull "$IMAGE"

echo "[2/5] 权重（DreamEternal/MinerU-Popo @ ${REVISION}）"
if [ -f "${POPO_MODEL_DIR}/config.json" ]; then
  echo "  已存在，跳过下载"
elif [ "$USE_MODELSCOPE" = "1" ]; then
  command -v modelscope >/dev/null || { echo "POPO_USE_MODELSCOPE=1 但未安装 modelscope CLI（pip install modelscope）" >&2; exit 1; }
  echo "  源 ModelScope"
  mkdir -p "$(dirname "$POPO_MODEL_DIR")"
  modelscope download --model DreamEternal/MinerU-Popo --local_dir "$POPO_MODEL_DIR"
else
  echo "  源 ${HF_ENDPOINT}"
  mkdir -p "$(dirname "$POPO_MODEL_DIR")"
  hf download DreamEternal/MinerU-Popo --local-dir "$POPO_MODEL_DIR"
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

if [ "$START" -eq 0 ]; then
  echo "[4/5] 跳过启动（--no-start）；后续: docker compose -f $DEPLOY_DIR/compose.yaml --env-file $ENV_FILE up -d"
  echo "[5/5] 跳过健康检查（--no-start）"
  echo "准备完成，未启动容器。"
  exit 0
fi

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
