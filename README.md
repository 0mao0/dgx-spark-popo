# dgx-spark-popo

PoPo 文档解析：DGX Spark（GB10）一键部署件 + Python 客户端库。

基于 [opendatalab/MinerU-Popo](https://github.com/opendatalab/MinerU-Popo) @ `8b9a8bd`（MIT），仅改一个文件；非官方衍生，与上游无隶属关系。

## 它解决什么

- 在 DGX Spark 上以 fp8 量化跑 Popo 4B 视觉判定引擎，采样参数经代理对齐官方 `generation_config`（`setdefault` 语义，显式传参被尊重）。
- 客户端三段链（label 归一化 → 4B 判定 → 文档树构建）独立安装，import 路径与上游一致：`popo.post_processing.*`。
- 相对上游的单文件补丁（`post_processing/model_utils.py`）：
  - `POPO_CONFIGS`：多端点 JSON 列表，数组顺序即 failover 顺序；
  - `POPO_API_TIMEOUT` / `POPO_MAX_TOKENS`：每端点超时与生成长度上限；
  - `POPO_TEMPERATURE`：默认 `1` 保持上游行为；设 `0` 走贪心解码（回归测试确定性用）。
- 单页文档判定：上游 `6fd49e4` 起 `adaptive_chunk` 对单页短路——此前单页文档不产生任何判定。

## 快速开始

部署（DGX Spark 主机，约 30GB 镜像 + 权重下载）：

```bash
cd deploy
cp .env.example .env     # 填 POPO_API_KEY 与模型路径
./deploy.sh              # 拉镜像 → 拉权重 → 打配置补丁 → 起容器 → 轮询 /health
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
 └─ popo-engine 127.0.0.1:8010   vLLM fp8
```

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

## 已知限制

- >10MB 大 PDF 并发解析可触发引擎 OOM（退出码 137）；单并发规避，`docker restart popo-engine` 恢复。
- 镜像约 30.3GB；直连 ghcr 慢时用 `ghcr.nju.edu.cn` 镜像前缀或 `docker save/load` 离线导入。

## 许可与致谢

MIT（与上游一致），见 `LICENSE`、`NOTICE`、`THIRD_PARTY_NOTICES.md`。

- 上游：[opendatalab/MinerU-Popo](https://github.com/opendatalab/MinerU-Popo)，env 端点方案已随 PR [#14](https://github.com/opendatalab/MinerU-Popo/pull/14) 并入上游；多端点 `POPO_CONFIGS` 为本仓补丁独有。
- 权重：`DreamEternal/MinerU-Popo @ af75342`，不转存，部署脚本按 revision 原仓拉取。
- 引擎依赖 vLLM（Apache-2.0）。
