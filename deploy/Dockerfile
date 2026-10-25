# GB10 (DGX Spark, arm64) PoPo 引擎镜像 —— 配方构建文件
# 依据 deploy/image-recipe.md 与 requirements-freeze.txt（现役 mineru-b:3.4.5 的依赖快照）。
# 注意：在干净 GB10 机器上构建即用；参数组合与现役生产一致但未经第三方机器验证，
# 构建失败时按 freeze 快照逐项对版本。
FROM python:3.12-slim

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_NO_CACHE_DIR=1 \
    HF_HUB_DISABLE_XET=1

# 基础工具（健康检查用 curl；git 供 trust-remote-code 场景）
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# 核心：torch cu128(aarch64 wheel 自带 CUDA 运行库) -> vllm(aarch64 wheel) -> mineru
# torch 必须先于 vllm 单独装（钉 cu128 index），其余按 PyPI 解析
RUN pip install --index-url https://download.pytorch.org/whl/cu128 \
        torch==2.11.0 torchvision==0.26.0 \
    && pip install \
        vllm==0.21.0 \
        triton==3.6.0 \
        transformers==4.57.6 \
        flashinfer-python==0.6.8.post1 \
        fastar==0.12.0 \
        mineru==3.4.5 \
        httpx fastapi uvicorn

# proxy 容器复用本镜像跑 popo_proxy.py（上一步已含其依赖）
WORKDIR /workspace
EXPOSE 8008 8010
CMD ["vllm", "serve", "--help"]
