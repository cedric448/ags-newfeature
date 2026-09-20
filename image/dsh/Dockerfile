# DeepSeek Harness on AGS —— 基于 AGS 公共代码沙箱镜像构建
#
# 基础镜像来自 AGS 公共 code-interpreter 沙箱（等价于 e2bdev/code-interpreter）：
#   - Debian 13 (trixie)、Python 3.12、Node 20
#   - 已内置 envd (/usr/bin/envd)，满足 AGS 自定义沙箱的探针要求
#
# 在原官方 Dockerfile（node:24-bookworm-slim）基础上做了两处适配：
#   1. 基础镜像换成 AGS 公共 code 沙箱镜像，复用其 Python/Node/envd/科学计算栈
#   2. 增加自定义 base URL 支持（DSH_LLM_BASE_URL / DSH_LLM_MODEL / DSH_LLM_API_KEY）

ARG BASE_IMAGE=ccr.ccs.tencentyun.com/ags-image/sandbox-code:latest
ARG NODE_IMAGE=docker.io/library/node:24.8.0-bookworm-slim

# ============================ build 阶段 ============================
FROM --platform=${BUILDPLATFORM} ${NODE_IMAGE} AS build

ARG DEEPSEEK_HARNESS_TAG=dsh-v0.1.1-rc.2
ARG DEEPSEEK_HARNESS_COMMIT=b150a551b8d465e31e418e1b2eaf5e79bbb7d28e
# 构建时可选代理（apt 已改国内镜像直连；git/npm 访问 GitHub/npmjs 需要代理）
ARG BUILD_HTTP_PROXY=""
ARG BUILD_HTTPS_PROXY=""

# 使用国内镜像源加速 apt（构建环境访问 deb.debian.org 慢）
RUN set -eux; \
    if [ -f /etc/apt/sources.list.d/debian.sources ]; then \
      sed -i 's|deb.debian.org|mirrors.tencent.com|g; s|security.debian.org|mirrors.tencent.com|g' \
        /etc/apt/sources.list.d/debian.sources; \
    fi; \
    if [ -f /etc/apt/sources.list ]; then \
      sed -i 's|deb.debian.org|mirrors.tencent.com|g; s|security.debian.org|mirrors.tencent.com|g' \
        /etc/apt/sources.list; \
    fi

RUN apt-get update \
    && apt-get install --yes --no-install-recommends ca-certificates git g++ make python3 \
    && rm -rf /var/lib/apt/lists/*

RUN npm install --global pnpm@11.7.0

WORKDIR /opt


RUN if [ -n "$BUILD_HTTP_PROXY" ]; then \
      git config --global http.proxy "$BUILD_HTTP_PROXY"; \
      git config --global https.proxy "$BUILD_HTTPS_PROXY"; \
    fi; \
    git clone --depth 1 --branch "$DEEPSEEK_HARNESS_TAG" \
      https://github.com/deepseek-ai/deepseek-harness.git \
      /opt/deepseek-harness \
    && git -C /opt/deepseek-harness rev-parse HEAD | grep --fixed-strings --line-regexp "$DEEPSEEK_HARNESS_COMMIT"

COPY 0001-support-ags-deployment-web.patch /tmp/0001-support-ags-deployment-web.patch

WORKDIR /opt/deepseek-harness

RUN git apply --unidiff-zero --check /tmp/0001-support-ags-deployment-web.patch \
    && git apply --unidiff-zero /tmp/0001-support-ags-deployment-web.patch

RUN if [ -n "$BUILD_HTTP_PROXY" ]; then \
      pnpm config set proxy "$BUILD_HTTP_PROXY"; \
      pnpm config set https-proxy "$BUILD_HTTPS_PROXY"; \
      npm config set proxy "$BUILD_HTTP_PROXY"; \
      npm config set https-proxy "$BUILD_HTTPS_PROXY"; \
    fi; \
    pnpm install --frozen-lockfile

RUN pnpm run build:official

RUN pnpm release:pack --family vendor --out dist/npm-vendor \
    && pnpm release:pack --family dsh --out dist/npm-dsh

# ====================== 运行阶段（AGS 基础镜像） ======================
FROM --platform=linux/amd64 ${BASE_IMAGE}

ARG BUILD_HTTPS_PROXY=""

# DSH 需要 Node >= 22（用到 node:module 的 stripTypeScriptTypes），
# 而 AGS 公共 code 沙箱基础镜像自带 Node 20，因此在此升级。
# envd 等 AGS 必需组件不受影响。
ARG NODE_VERSION=24.8.0
RUN set -eux; \
    arch="$(dpkg --print-architecture)"; \
    case "$arch" in \
      amd64) narch=x64 ;; \
      arm64) narch=arm64 ;; \
      *) echo "unsupported arch: $arch" >&2; exit 1 ;; \
    esac; \
    base="https://nodejs.org/dist/v${NODE_VERSION}/node-v${NODE_VERSION}-linux-${narch}"; \
    if [ -n "${BUILD_HTTPS_PROXY}" ]; then \
      curl -fsSL -x "${BUILD_HTTPS_PROXY}" -o /tmp/node.tar.xz "${base}.tar.xz"; \
    else \
      curl -fsSL -o /tmp/node.tar.xz "${base}.tar.xz"; \
    fi; \
    tar -xJf /tmp/node.tar.xz -C /usr/local --strip-components=1 \
      --exclude=CHANGELOG.md --exclude=LICENSE --exclude=README.md; \
    rm /tmp/node.tar.xz; \
    node -v; npm -v

# 构建产物：DSH 及其 vendor 依赖的 npm 包
COPY --from=build /opt/deepseek-harness/dist/npm-vendor /tmp/vendor-tarballs
COPY --from=build /opt/deepseek-harness/dist/npm-dsh /tmp/dsh-tarballs

# 安装到全局。基础镜像的 Node/npm 已就绪
RUN npm install --global --no-audit --no-fund --omit=optional \
      /tmp/vendor-tarballs/*.tgz \
      /tmp/dsh-tarballs/*.tgz \
    && rm -rf /tmp/vendor-tarballs /tmp/dsh-tarballs /root/.npm

# ---------- 自定义 base URL 支持 ----------
# DSH 通过配置文件 /root/.dsh/config 读取 LLM 提供方设置。
# 这里提供环境变量入口，由 entrypoint 在启动时渲染成配置，
# 便于在 AGS 上按实例覆盖 model / baseURL / apiKey。
ENV DSH_HOME=/root/.dsh \
    DSH_LLM_BASE_URL="" \
    DSH_LLM_MODEL="" \
    DSH_LLM_API_KEY="" \
    DSH_WEB_PORT=3080 \
    DSH_TRUSTED_HOST="*.tencentags.com"

COPY entrypoint.sh /usr/local/bin/dsh-ags-entrypoint.sh
RUN chmod +x /usr/local/bin/dsh-ags-entrypoint.sh

WORKDIR /workspace

# AGS 探针与数据面端口：
#   3080 —— DSH Web 界面
#   49983 —— envd（AGS 必需的探针端口）
EXPOSE 3080 49983

ENTRYPOINT ["/usr/local/bin/dsh-ags-entrypoint.sh"]
