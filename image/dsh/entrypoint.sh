#!/usr/bin/env sh
# AGS 上运行 DeepSeek Harness 的入口脚本。
#
# 职责：
#   1. 根据环境变量渲染 $DSH_HOME/settings.yaml（自定义 base URL / model / compat）
#   2. 根据环境变量写 $DSH_HOME/.credentials.yaml（API Key，仅本机可读）
#   3. 启动 envd（AGS 探针依赖，端口 49983）
#   4. 前台启动 DSH Web（端口 3080）
#
# 可配置环境变量：
#   DSH_PROVIDER_ID    提供方 ID，默认 deepseek（须以小写字母开头）
#   DSH_LLM_BASE_URL   自定义 base URL，例如 https://tokenhub.tencentmaas.com/v1
#   DSH_LLM_MODEL      模型 ID，例如 deepseek/deepseek-flash
#   DSH_LLM_API_KEY    API Key（Bearer token）
#   DSH_WEB_PORT       Web 端口，默认 3080
#   DSH_TRUSTED_HOST   受信主机通配符，默认 *.tencentags.com
#   DSH_MAX_TOKENS_FIELD  max_tokens 或 max_completion_tokens（默认 max_completion_tokens）
#   DSH_SUPPORTS_DEVELOPER_ROLE  true/false，默认 false（兼容多数网关）

set -eu

DSH_HOME="${DSH_HOME:-/root/.dsh}"
DSH_WEB_PORT="${DSH_WEB_PORT:-3080}"
DSH_TRUSTED_HOST="${DSH_TRUSTED_HOST:-*.tencentags.com}"
DSH_PROVIDER_ID="${DSH_PROVIDER_ID:-deepseek}"
DSH_LLM_BASE_URL="${DSH_LLM_BASE_URL:-}"
DSH_LLM_MODEL="${DSH_LLM_MODEL:-}"
DSH_LLM_API_KEY="${DSH_LLM_API_KEY:-}"
DSH_MAX_TOKENS_FIELD="${DSH_MAX_TOKENS_FIELD:-max_completion_tokens}"
DSH_SUPPORTS_DEVELOPER_ROLE="${DSH_SUPPORTS_DEVELOPER_ROLE:-false}"

mkdir -p "$DSH_HOME"

# ---------------------------------------------------------------- 渲染配置
if [ -n "$DSH_LLM_BASE_URL" ] || [ -n "$DSH_LLM_MODEL" ]; then
  echo "[dsh-ags] 渲染 settings.yaml（provider=${DSH_PROVIDER_ID}）"

  API_KEY_ENV="$(echo "${DSH_PROVIDER_ID}_API_KEY" | tr '[:lower:]-' '[:upper:]_')"

  : > "${DSH_HOME}/settings.yaml"

  if [ -n "$DSH_LLM_MODEL" ]; then
    cat >> "${DSH_HOME}/settings.yaml" <<YAML
llm-pi-ai:
  providers:
    ${DSH_PROVIDER_ID}:
      apiKeyEnv: ${API_KEY_ENV}
      api: openai-completions
YAML
    if [ -n "$DSH_LLM_BASE_URL" ]; then
      echo "      baseURL: ${DSH_LLM_BASE_URL}" >> "${DSH_HOME}/settings.yaml"
    fi
    cat >> "${DSH_HOME}/settings.yaml" <<YAML
      compat:
        supportsDeveloperRole: ${DSH_SUPPORTS_DEVELOPER_ROLE}
        maxTokensField: ${DSH_MAX_TOKENS_FIELD}
      models:
        - id: ${DSH_LLM_MODEL}
YAML
  fi
else
  echo "[dsh-ags] 未提供 DSH_LLM_BASE_URL / DSH_LLM_MODEL，跳过 settings.yaml 渲染"
fi

# ---------------------------------------------------------------- 渲染凭证
if [ -n "$DSH_LLM_API_KEY" ]; then
  API_KEY_ENV="$(echo "${DSH_PROVIDER_ID}_API_KEY" | tr '[:lower:]-' '[:upper:]_')"
  echo "[dsh-ags] 写入 .credentials.yaml（${API_KEY_ENV}）"
  umask 077
  cat > "${DSH_HOME}/.credentials.yaml" <<YAML
${API_KEY_ENV}: "${DSH_LLM_API_KEY}"
YAML
  chmod 600 "${DSH_HOME}/.credentials.yaml"
else
  echo "[dsh-ags] 未提供 DSH_LLM_API_KEY，将使用已有凭证配置"
fi

# 让 DSH 能读到同一份凭证环境变量
if [ -n "$DSH_LLM_API_KEY" ]; then
  API_KEY_ENV="$(echo "${DSH_PROVIDER_ID}_API_KEY" | tr '[:lower:]-' '[:upper:]_')"
  export "${API_KEY_ENV}=${DSH_LLM_API_KEY}"
fi

if [ -f "${DSH_HOME}/settings.yaml" ]; then
  echo "[dsh-ags] settings.yaml:"
  sed 's/^/    /' "${DSH_HOME}/settings.yaml"
fi

# ---------------------------------------------------------------- 启动 envd
ENVD_BIN=""
for p in /usr/bin/envd /usr/local/bin/envd /mnt/envd-runtime/envd; do
  if [ -x "$p" ]; then ENVD_BIN="$p"; break; fi
done

if [ -n "$ENVD_BIN" ]; then
  echo "[dsh-ags] 启动 envd: $ENVD_BIN"
  "$ENVD_BIN" -port 49983 >/tmp/envd.log 2>&1 &
else
  echo "[dsh-ags] 警告：未找到 envd，AGS 探针可能失败" >&2
fi

# ---------------------------------------------------------------- 启动 DSH
# 优先用 PATH 中的 dsh（npm 全局安装，AGS 基础镜像的 npm root 为 /usr/lib）
DSH_BIN="$(readlink -f "$(command -v dsh || true)" 2>/dev/null || true)"
if [ -z "$DSH_BIN" ] || [ ! -f "$DSH_BIN" ]; then
  for p in /usr/lib/node_modules/@deepseek-ai/dsh/lib/bin.js \
           /usr/local/lib/node_modules/@deepseek-ai/dsh/lib/bin.js; do
    if [ -f "$p" ]; then DSH_BIN="$p"; break; fi
  done
fi

if [ -z "$DSH_BIN" ] || [ ! -f "$DSH_BIN" ]; then
  echo "[dsh-ags] 错误：找不到 dsh 可执行文件" >&2
  exit 1
fi

set -- web --host 0.0.0.0 --port "$DSH_WEB_PORT" --no-open
# trusted-host 支持逗号分隔的多个值
OLD_IFS="$IFS"; IFS=','
for h in $DSH_TRUSTED_HOST; do
  [ -n "$h" ] && set -- "$@" --trusted-host "$h"
done
IFS="$OLD_IFS"
set -- "$@" --allow-remote-management

echo "[dsh-ags] 启动 DSH: node --expose-internals $DSH_BIN $*"
exec node --expose-internals "$DSH_BIN" "$@"
