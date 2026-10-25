# Release Notes

## v0.1.0（首个公开版）

PoPo 文档解析：DGX Spark（GB10）一键部署件 + Python 客户端库。基于 [opendatalab/MinerU-Popo](https://github.com/opendatalab/MinerU-Popo) @ `8b9a8bd`（MIT），非官方衍生。

### 包含

- **客户端库 `popo-client`**：import 路径与上游一致（`popo.post_processing.*`），三段链（label 归一化 → 4B 判定 → 文档树）独立安装。
- **单文件补丁**（`post_processing/model_utils.py`）：
  - `POPO_CONFIGS`：多端点 JSON 列表，数组顺序即 failover 顺序；
  - `POPO_API_TIMEOUT` / `POPO_MAX_TOKENS`：每端点超时与生成长度；
  - `POPO_TEMPERATURE`：默认 `1` 保持上游行为，设 `0` 走贪心解码（测试确定性用）。
- **部署件 `deploy/`**：`deploy.sh` 五步一键部署（拉镜像 → 拉权重 → 打 preprocessor 配置补丁 → 起两容器 → 轮询 `/health`）；引擎 fp8 量化，采样代理按官方 `generation_config` 注入默认参数（`setdefault` 语义，显式传参被尊重）。
- **测试工具 `scripts/`**：三段链 runner、构树 JSON 白名单差分、贪心代理、冒烟/差分编排、上游提交跟踪。

### 相对旧内化版本的改进（随上游 `8b9a8bd` 带来）

- **单页文档判定修复**（上游 `6fd49e4`）：旧版 `adaptive_chunk` 对单页文档返回空块列表——单页文档此前不产生任何引擎判定；本版单页正常产出 title/level 判定。
- 标题进树（`8b9a8bd`）：深层节点 `title` 由空值填充为正文标题；`img_path` / `caption` / `table_body` 保留并做 bbox 匹配。
- 标题标签识别 `doc_title` / `paragraph_title`（`452f255`）。

### 测试结论（内部冻结语料 100 本口径）

- 差分（贪心解码）：10/10 通过——其中单页 2 本按放宽判据（树有效、判定非空），多页 8 本中 5 本逐字节一致、2 本仅 title 空值填充、1 本（10-K 表密集文档）分节策略差异经人工裁决接受。
- 影子对比（生产参数 30 本）：p50/p95 持平，零 5xx / timeout / 端点失败。
- 确定性：贪心解码下同输入两次构树逐字节一致。

### 已知限制

- **大 PDF 并发 OOM**：>10MB PDF 并发解析可触发引擎 OOM（容器退出码 137）；单并发规避，`docker restart popo-engine` 恢复。
- **镜像不分发（BYO）**：GB10（arm64）vLLM 环境自备，`POPO_IMAGE` 参数化指向你的镜像；CUDA13/arm64 wheel 可得性是自建门槛。
- 引擎参数 `--gpu-memory-utilization 0.17` 按 GB10 与其他服务共存的口径调校，独占机型可自行调高。

### 权重

不随仓分发。部署脚本按 revision 锁定从 `DreamEternal/MinerU-Popo @ af75342` 拉取。

### 致谢

- 上游 [opendatalab/MinerU-Popo](https://github.com/opendatalab/MinerU-Popo)；env 端点方案已随 PR [#14](https://github.com/opendatalab/MinerU-Popo/pull/14) 并入上游，多端点 `POPO_CONFIGS` 为本仓补丁独有。
- 引擎 vLLM（Apache-2.0）。
