# dgx-spark-popo

PoPo 文档解析：客户端后处理库 + DGX Spark 一键部署件。

基于 [opendatalab/MinerU-Popo](https://github.com/opendatalab/MinerU-Popo) @ `8b9a8bd`，仅改一个文件（`post_processing/model_utils.py`：`POPO_CONFIGS` 多端点配置 + 超时 + `POPO_MAX_TOKENS`）。非官方衍生，与上游无隶属关系。

## 仓库结构

| 路径 | 内容 |
|---|---|
| `src/popo/` | 上游 `8b9a8bd` 全量代码 + 单文件补丁；import 路径 `popo.post_processing.*` |
| `deploy/` | 引擎镜像、compose、代理、systemd（M7 交付） |
| `scripts/` | `check_upstream.sh` 上游跟踪；冒烟脚本（M2 交付） |

## 安装

```bash
pip install "popo-client @ git+https://github.com/0mao0/dgx-spark-popo@v0.1.0"
```

```python
from popo.post_processing import label_normalization
```

## 部署

`deploy.sh` 一键装通（M7 交付）：拉镜像 → 拉权重（`HF_HUB_DISABLE_XET=1`）→ 打配置补丁 → 起两容器 → 轮询 `/health`。

## 权重

不随仓分发。指向 `DreamEternal/MinerU-Popo @ af75342`，由部署脚本按 revision 拉取。

## 许可

MIT（与上游一致）。见 `LICENSE`、`NOTICE`、`THIRD_PARTY_NOTICES.md`。
