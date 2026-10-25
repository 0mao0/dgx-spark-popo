# GB10 引擎镜像配方（参考）

本仓**不分发镜像**（BYO）。以下是现役生产镜像（mineru-b:3.4.5，DGX Spark GB10）的依赖配方，
供自建镜像参考；完整 pip freeze 见 `requirements-freeze.txt`（267 项快照）。

## 关键版本

| 包 | 版本 | 备注 |
|---|---|---|
| vllm | 0.21.0 | **aarch64 自建 wheel**（manylinux_2_24_aarch64, cp38-abi3），PyPI 无此构建 |
| torch | 2.11.0+cu128 | 配套 torchvision 0.26.0+cu128 |
| triton | 3.6.0 | |
| transformers | 4.57.6 | |
| mineru | 3.4.5 | 镜像即其运行环境 |
| flashinfer-python | 0.6.8.post1 | aliyun 镜像 wheel |
| fastar | 0.12.0 | |
| CUDA | cu12.8 包 + cuda-toolkit 13 系列混布 | nvidia-cublas 13.1 / cu12 12.8 并存 |

## 构建要点（GB10 / arm64）

1. 最大门槛是 vllm 的 aarch64 wheel：官方 PyPI 无对应构建，需自行编译或取社区构建；
   torch/cu128 与 CUDA13 运行库按 freeze 清单钉版本装。
2. 镜像需提供 `vllm serve` CLI 与 python3（proxy 容器复用同一镜像跑 `popo_proxy.py`，
   仅需 httpx/fastapi/uvicorn）。
3. 权重不进镜像：挂载 `~/models/MinerU-Popo`（ro），见 compose.yaml。

## 生产启动参数（与 compose 一致）

`--quantization fp8 --dtype bfloat16 --max-model-len 32768 --max-num-seqs 4
--gpu-memory-utilization 0.17 --trust-remote-code`（gmu=0.17 为与其他服务共存的口径，独占可调高）
