# deploy（M7）

PoPo 引擎 + 采样代理的一键部署件，目标平台 DGX Spark（GB10）。

## 快速开始

```bash
cp .env.example .env        # 填 POPO_API_KEY、POPO_IMAGE 与模型路径
./deploy.sh                 # 拉镜像 → 拉权重 → 打配置补丁 → 起容器 → 轮询 /health
```

成功后：`http://<host>:8008/health` 200，vLLM 引擎只绑 `127.0.0.1:8010`。

## 镜像（BYO）

**不随仓分发镜像**。`POPO_IMAGE` 指向任意满足以下条件的 GB10（arm64）镜像：

- 提供 `vllm serve` CLI 与 Python 3（proxy 容器用它跑 `popo_proxy.py`，仅标准依赖 httpx/fastapi/uvicorn）；
- 能加载 Popo 4B fp8（vLLM ≥ 你的构建所支持的 fp8 量化路径）。

没有现成镜像时，需自行构建 GB10 兼容的 vLLM 环境（CUDA 13 / arm64 wheel 可得性是主要门槛）。

## 文件

| 文件 | 说明 |
|---|---|
| `deploy.sh` | 五步部署；权重 `DreamEternal/MinerU-Popo@af75342`，`HF_HUB_DISABLE_XET=1` |
| `compose.yaml` | engine（vLLM fp8，参数与现役一致）+ proxy（采样注入，host 网络） |
| `popo_proxy.py` | 80 行采样代理：`setdefault` 注入 0.7/0.8/20，显式传参被尊重 |
| `.env.example` | 端口、密钥、模型路径、采样参数 |
| `systemd/` | 可选开机单元 |

## 客户端调用

```python
from openai import OpenAI
client = OpenAI(base_url="http://<host>:8008/v1", api_key="<POPO_API_KEY>")
```

后处理库用法见仓库根 README；`pip install popo-client` 后按 `popo.post_processing` 三段链跑（见 `scripts/run_popo_chain.py` 的 docstring）。

## 已知限制

- **大 PDF 并发 OOM**：>10MB PDF 并发解析可触发引擎 OOM（容器退出码 137）；单并发规避，重启 `docker restart popo-engine` 恢复。
- 镜像 BYO（见上节），不提供 GHCR 分发；`docker save/load` 离线迁移自备镜像即可。
- 单页文档判定修复（相对 8b9a8bd 之前的旧版）由 6fd49e4 带来，见主 README 与 release notes。
