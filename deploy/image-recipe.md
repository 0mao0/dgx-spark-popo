# GB10 引擎镜像配方（参考）

本仓**不分发镜像**（BYO）。以下是现役生产镜像（mineru-b:3.4.5，DGX Spark GB10）的依赖配方，
供自建镜像参考；完整 pip freeze 见 `requirements-freeze.txt`（267 项快照）。

## 下载来源

| 内容 | 来源 | 说明 |
|---|---|---|
| vllm 0.21.0（aarch64） | `pip install vllm==0.21.0` | **PyPI 官方含 manylinux aarch64 wheel**；现役镜像用本地构建 wheel 属历史产物，与官方包等位 |
| torch 2.11.0+cu128（aarch64） | `pip install torch==2.11.0 --index-url https://download.pytorch.org/whl/cu128` | 官方 index 提供 manylinux_2_28_aarch64 |
| mineru 3.4.5 | `pip install mineru==3.4.5` | PyPI |
| Popo 权重 | `hf download DreamEternal/MinerU-Popo --revision af75342` | https://huggingface.co/DreamEternal/MinerU-Popo/tree/af75342 ；国内可加 `HF_ENDPOINT=https://hf-mirror.com`；下载务必 `HF_HUB_DISABLE_XET=1` |
| 上游代码 | https://github.com/opendatalab/MinerU-Popo | 本仓 src/popo 即其 8b9a8bd + 单文件补丁 |

## 关键版本

| 包 | 版本 | 备注 |
|---|---|---|
| vllm | 0.21.0 | PyPI aarch64 wheel（cp38-abi3） |
| torch | 2.11.0+cu128 | 配套 torchvision 0.26.0+cu128 |
| triton | 3.6.0 | |
| transformers | 4.57.6 | |
| mineru | 3.4.5 | 镜像即其运行环境 |
| flashinfer-python | 0.6.8.post1 | |
| CUDA | cu12.8 包 + cuda-toolkit 13 系列混布 | nvidia-cublas 13.1 / cu12 12.8 并存 |

## 构建要点（GB10 / arm64）

1. 基础镜像建议 Ubuntu/Debian arm64 + CUDA 运行时（GB10 用 cuda-toolkit 13 系列运行库，
   具体 pip 依赖按 freeze 清单钉版本）。
2. 镜像需提供 `vllm serve` CLI 与 python3（proxy 容器复用同一镜像跑 `popo_proxy.py`，
   仅需 httpx/fastapi/uvicorn）。
3. 权重不进镜像：挂载 `~/models/MinerU-Popo`（ro），见 compose.yaml。

## 生产启动参数（与 compose 一致）

`--quantization fp8 --dtype bfloat16 --max-model-len 32768 --max-num-seqs 4
--gpu-memory-utilization 0.17 --trust-remote-code`（gmu=0.17 为与其他服务共存的口径，独占可调高）
