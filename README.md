# dgx-spark-popo

PoPo 文档解析：DGX Spark（GB10）一键部署件 + Python 客户端库。

基于 [opendatalab/MinerU-Popo](https://github.com/opendatalab/MinerU-Popo) @ `8b9a8bd`（MIT），仅改一个文件；非官方衍生，与上游无隶属关系。

## 它解决什么

- 在 DGX Spark 上以 fp8 量化跑 Popo 4B 视觉判定引擎，采样参数经代理对齐官方 `generation_config`（`setdefault` 语义，显式传参被尊重）。
- 客户端三段链（label 归一化 → 4B 判定 → 文档树构建）独立安装，import 路径与上游一致：`popo.post_processing.*`。
- 相对上游的单文件补丁（`post_processing/model_utils.py`）：
  - `POPO_CONFIGS`：多端点 JSON 列表，数组顺序即 failover 顺序；
  - `POPO_API_TIMEOUT` / `POPO_MAX_TOKENS`：每端点超时与生成长度上限；
  - `POPO_TEMPERATURE`：默认**不发送**该参数（由服务端/采样代理注入官方默认）；设 `0` 贪心解码（差分确定性），设 `1` 复现旧版显式行为（会打穿代理修复、放大空输出，不建议）。
- 单页文档判定：上游 `6fd49e4` 起 `adaptive_chunk` 对单页短路——此前单页文档不产生任何判定。

## 快速开始

部署（DGX Spark 主机；**镜像 BYO**——`POPO_IMAGE` 指向你的 GB10 vLLM 镜像，权重按 revision 拉取）：

```bash
cd deploy
cp .env.example .env     # 填 POPO_API_KEY、POPO_IMAGE 与模型路径
./deploy.sh              # 拉镜像 → 拉权重 → 打配置补丁 → 起容器 → 轮询 /health
./deploy.sh --no-start   # 可选：只做准备工作（镜像/权重/补丁），不启动容器
```

成功后 `http://<host>:8008/health` 返回 200，引擎只绑 `127.0.0.1:8010`。

客户端库（调用方机器）：

```bash
pip install "popo-client @ git+https://github.com/0mao0/dgx-spark-popo@v0.1.0"
```

## 架构

```
PDF ──> MinerU 解析（外部前置，本仓不含）
 │         └─ middle.json
 ▼
popo.post_processing 三段链
 ├─ label_normalization.py   label 归一化
 ├─ run_inference.py         HTTP :8008，判定 title/contd/image
 └─ get_json_tree.py         文档树 JSON
        │
        ▼
deploy/（本仓）           DGX Spark 主机
 ├─ popo-api  :8008       采样代理（setdefault 0.7/0.8/20）
 ├─ popo-engine 127.0.0.1:8010   vLLM fp8
 └─ popo-docapi :8009（可选）  文档级 API：POST middle.json+PDF → 判定+树（server/）
```

两种接入形态：**文档级**（推荐外部使用者）——`docker compose --profile docapi up -d` 后
`POST :8009/v1/enhance`（multipart：middle + pdf），见 `server/popo_api.py`；
**链级**（库内编排，AnGIneer 现行）——`pip install popo-client` 跑三段链，直连 :8008。

引擎生产参数：`--quantization fp8 --dtype bfloat16 --max-model-len 32768 --max-num-seqs 4 --gpu-memory-utilization 0.17 --trust-remote-code`。

## 配置

客户端环境变量：

| 变量 | 默认 | 说明 |
|---|---|---|
| `POPO_CONFIGS` | 必填 | JSON 列表 `[{"name","url","api_key","model"}]`，顺序 failover |
| `POPO_API_TIMEOUT` | 300 | 单端点超时（秒） |
| `POPO_MAX_TOKENS` | 4096 | 生成长度上限 |
| `POPO_TEMPERATURE` | 1 | 设 0 贪心解码 |

部署配置见 `deploy/.env.example`（密钥、模型路径、端口、代理采样参数）。

## 测试

| 脚本 | 用途 |
|---|---|
| `scripts/run_popo_chain.py` | 对给定文档跑三段链 |
| `scripts/diff_trees.py` | 构树 JSON 白名单差分 |
| `scripts/smoke_diff.py` | 冒烟 / 十本差分 / 影子对比编排 |
| `scripts/greedy_proxy.py` | 旧版本侧强制贪心的本地转发代理 |
| `scripts/check_upstream.sh` | 上游新提交跟踪 |

冻结集机制：回归清单（doc id + sha256 + 页数 + 分层）由调用方经 `POPO_FROZEN_MANIFEST` 注入，不入仓；CI 无清单时只跑单测。差分确定性口径：`POPO_TEMPERATURE=0` 两次构树逐字节一致。

## 与上游的差异

- `src/popo` = [上游](https://github.com/opendatalab/MinerU-Popo) `8b9a8bd` 全量文件，**仅 `post_processing/model_utils.py` 一个文件带补丁**（其余文件与上游逐字节一致）：`POPO_CONFIGS` 多端点、超时、`POPO_MAX_TOKENS`、`POPO_TEMPERATURE`、单对象配置容错。
- 仓级新增（不属于上游代码）：`deploy/` 部署件、`scripts/` 测试工具链、`tests/`、CI、本文件与 NOTICES。
- 权重下载：[HF DreamEternal/MinerU-Popo @ af75342](https://huggingface.co/DreamEternal/MinerU-Popo/tree/af75342)（`HF_HUB_DISABLE_XET=1`；国内可设 `HF_ENDPOINT=https://hf-mirror.com`）；引擎镜像自建见 [deploy/image-recipe.md](deploy/image-recipe.md)（vllm/torch aarch64 下载来源在内）。
- 包下载：uv 默认走阿里云 PyPI 镜像（仓内 `pyproject.toml` `[[tool.uv.index]]`，机器级 `~/.config/uv/uv.toml`；`UV_DEFAULT_INDEX` 可临时覆盖）。

## 已知限制

- >10MB 大 PDF 并发解析可触发引擎 OOM（退出码 137）；单并发规避，`docker restart popo-engine` 恢复。
- **镜像不分发**：GB10（arm64）vLLM 环境自备，`POPO_IMAGE` 参数化；CUDA13/arm64 wheel 可得性是自建门槛。

## 许可与致谢

MIT（与上游一致），见 `LICENSE`、`NOTICE`、`THIRD_PARTY_NOTICES.md`。

- 上游：[opendatalab/MinerU-Popo](https://github.com/opendatalab/MinerU-Popo)，env 端点方案已随 PR [#14](https://github.com/opendatalab/MinerU-Popo/pull/14) 并入上游；多端点 `POPO_CONFIGS` 为本仓补丁独有。
- FP8 在线量化：部署指南与等价性验证 harness 见上游 PR [#18](https://github.com/opendatalab/MinerU-Popo/pull/18)（本仓 deploy 的 `--quantization fp8` 引擎参数即按该方案）。
- 权重：`DreamEternal/MinerU-Popo @ af75342`，不转存，部署脚本按 revision 原仓拉取。
- 引擎依赖 vLLM（Apache-2.0）。
