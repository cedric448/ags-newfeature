# DeepSeek Harness on AGS —— 自定义镜像

把 DeepSeek Harness（DSH）打包成 AGS 可用的自定义沙箱镜像，并支持通过环境变量
配置**自定义 base URL**（对接公司网关 / 第三方 OpenAI 兼容端点）。

- 镜像地址：`euson-tcr.tencentcloudcr.com/cedricbwang/test:v1`
- digest：`sha256:e11a842a86142ee7003613c90c25e8b5d70a625a16b843ed43627371495a9d9e`
- DSH 版本：`0.1.1-rc.2`

## 基础镜像

从 AGS 公共代码沙箱镜像派生：

| 来源 | 说明 |
|---|---|
| `ccr.ccs.tencentyun.com/ags-image/sandbox-code:latest` | AGS 公共 code-interpreter 沙箱镜像（等价 `e2bdev/code-interpreter`） |
| 自带 | Debian 13 (trixie)、Python 3.12、Node 20、科学计算栈 |
| 自带 | **`/usr/bin/envd`** —— AGS 探针与数据面必需 |

与官方 DSH Dockerfile（基于 `node:24-bookworm-slim`）的差异：

1. **基础镜像换成 AGS 公共 code 沙箱镜像** —— 复用其 Python/科学计算/envd，符合你「从 AGS 公共镜像捞 base」的要求
2. **升级 Node 20 → 24** —— DSH 依赖 `node:module` 的 `stripTypeScriptTypes`（Node ≥22）
   与 `node:zlib` 的 `createZstdDecompress`（Node ≥23），基础镜像自带的 Node 20 跑不起来
3. **新增自定义 base URL 支持** —— 通过环境变量渲染 `settings.yaml` / `.credentials.yaml`
4. **改用国内 apt 镜像** —— 构建时 `deb.debian.org` 极慢

## 用法：在 AGS 上创建工具

镜像的 `ENTRYPOINT` 是 `/usr/local/bin/dsh-ags-entrypoint.sh`。AGS 要求显式给
`Command`/`Args`，因此创建工具时这样写：

```json
{
  "ToolName": "deepseek-harness",
  "ToolType": "custom",
  "NetworkConfiguration": {"NetworkMode": "PUBLIC"},
  "RoleArn": "qcs::cam::uin/100008634787:roleName/ags-tcr-full",
  "CustomConfiguration": {
    "Image": "euson-tcr.tencentcloudcr.com/cedricbwang/test:v1",
    "ImageRegistryType": "enterprise",
    "Command": ["sh"],
    "Args": ["-c", "/usr/local/bin/dsh-ags-entrypoint.sh"],
    "Env": [
      {"Name": "DSH_LLM_BASE_URL", "Value": "https://tokenhub.tencentmaas.com/v1"},
      {"Name": "DSH_LLM_MODEL",    "Value": "deepseek/deepseek-flash"},
      {"Name": "DSH_LLM_API_KEY",  "Value": "sk-..."}
    ],
    "Ports": [
      {"Name": "web",  "Port": 3080,  "Protocol": "TCP"},
      {"Name": "envd", "Port": 49983, "Protocol": "TCP"}
    ],
    "Resources": {"CPU": "2000m", "Memory": "4096Mi"},
    "Probe": {
      "HttpGet": {"Path": "/health", "Port": 49983, "Scheme": "HTTP"},
      "ReadyTimeoutMs": 30000, "ProbeTimeoutMs": 2000, "ProbePeriodMs": 3000,
      "SuccessThreshold": 1, "FailureThreshold": 100
    }
  }
}
```

> **探针必须指向 49983（envd）**，不能指向 3080。DSH 启动要几十秒，
> 指向 3080 会导致探针在就绪前超时。

## 环境变量

| 变量 | 默认值 | 说明 |
|---|---|---|
| `DSH_LLM_BASE_URL` | 空 | **自定义 base URL**，如 `https://tokenhub.tencentmaas.com/v1` |
| `DSH_LLM_MODEL` | 空 | 模型 ID，如 `deepseek/deepseek-flash` |
| `DSH_LLM_API_KEY` | 空 | API Key（Bearer token） |
| `DSH_PROVIDER_ID` | `deepseek` | 提供方 ID，须以小写字母开头 |
| `DSH_WEB_PORT` | `3080` | DSH Web 端口 |
| `DSH_TRUSTED_HOST` | `*.tencentags.com` | 受信主机，逗号分隔多个 |
| `DSH_MAX_TOKENS_FIELD` | `max_completion_tokens` | 兼容性：改 `max_tokens` 可适配只认旧字段的网关 |
| `DSH_SUPPORTS_DEVELOPER_ROLE` | `false` | 兼容性：网关拒绝 `role: developer` 时保持 false |

### 渲染结果

入口脚本会把环境变量渲染成 DSH 的配置文件：

`$DSH_HOME/settings.yaml`
```yaml
llm-pi-ai:
  providers:
    deepseek:
      apiKeyEnv: DEEPSEEK_API_KEY
      api: openai-completions
      baseURL: https://tokenhub.tencentmaas.com/v1
      compat:
        supportsDeveloperRole: false
        maxTokensField: max_completion_tokens
      models:
        - id: deepseek/deepseek-flash
```

`$DSH_HOME/.credentials.yaml`（权限 600）
```yaml
DEEPSEEK_API_KEY: "sk-..."
```

## 本地构建

```bash
cd image/dsh
docker build --network host --platform linux/amd64 \
  --build-arg BUILD_HTTP_PROXY=http://127.0.0.1:1087 \
  --build-arg BUILD_HTTPS_PROXY=http://127.0.0.1:1087 \
  -t euson-tcr.tencentcloudcr.com/cedricbwang/test:v1 .
```

> `--network host` + 代理参数只在需要翻墙的环境下需要（git clone GitHub / npm 下载）。
> apt 已改用 `mirrors.tencent.com` 直连，不走代理。

## 推送

```bash
docker login euson-tcr.tencentcloudcr.com -u <用户名> --password-stdin
docker push euson-tcr.tencentcloudcr.com/cedricbwang/test:v1
```

## 验证记录

| 项 | 结果 |
|---|---|
| AGS 拉取镜像并创建工具 | ✅ 工具 `ACTIVE`，digest 与推送一致 |
| 容器内 DSH 进程 | ✅ `node .../dsh/lib/bin.js web --host 0.0.0.0 --port 3080` |
| 容器内 `settings.yaml` | ✅ 正确渲染出自定义 baseURL / model / compat |
| 容器内 envd | ✅ `/health` 返回 204 |
| 容器内 Web UI（3080） | ✅ HTTP 200，返回真实 HTML |
| **AGS 公网数据面访问** | ✅ `https://3080-<instanceId>.ap-beijing.tencentags.com` 返回 200 |
| 自定义端点连通性 | ✅ `tokenhub.tencentmaas.com/v1/chat/completions` 实测返回中文回复 |
