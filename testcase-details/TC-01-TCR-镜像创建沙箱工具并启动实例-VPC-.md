# TC-01 TCR 镜像创建沙箱工具并启动实例（VPC）

| 项 | 值 |
|---|---|
| 结论 | **PASS** |
| 执行时间 | 2026-09-19 14:59:35 |
| 耗时 | 28.9s |
| 网络模式 | VPC |

## 测试目的

验证用 TCR 实例 `tcr-mvlaq1sq` 的镜像 `euson-tcr.tencentcloudcr.com/sandbox/sandbox:v1` 能否在 AGS 北京地域创建 custom 工具并成功启动沙箱实例，数据面可执行命令。这是所有后续测试例的前置基线。

## 前置条件

腾讯云凭据可用；TCR 镜像可访问；网络模式 VPC

## 测试步骤与结果

| # | 步骤 | 结论 | 耗时 | 说明 |
|---|------|------|------|------|
| 1 | 创建沙箱工具 CreateSandboxTool | ✅ PASS | 2.0s | ToolId=sdt-4mncnm4u |
| 2 | 等待工具状态 ACTIVE | ✅ PASS | 15.3s | 状态=ACTIVE |
| 3 | 镜像 digest 已解析 | ✅ PASS | 0.0s | digest=sha256:21b067114e8615b607b7b377e7a2e5ef8e6160c6525059f1d9628a9ec637003a |
| 4 | 启动沙箱实例 StartSandboxInstance | ✅ PASS | 4.3s | InstanceId=ywelopbyczp7peanfk4wtpfam4y4g2k6smtwqjf2 |
| 5 | 等待实例状态 RUNNING | ✅ PASS | 0.1s | 状态=RUNNING |
| 6 | E2B 连接沙箱实例 | ✅ PASS | 4.5s | sandbox_id=scslosfwup57psky2odvrakpmbsbflb262xsbghe |
| 7 | 数据面执行 shell 命令 | ✅ PASS | 0.0s | exit=0 |
| 8 | 文件 API 读写 | ✅ PASS | 0.0s | 写入后读回一致 |
| 9 | VPC 出网行为记录 | ✅ PASS | 0.0s | 结果=200 |
| 10 | 停止实例并确认回收 | ✅ PASS | 0.0s | 实例已进入终态 |

### 证据 1: 创建沙箱工具 CreateSandboxTool

```
{
  "ToolId": "sdt-4mncnm4u",
  "RequestId": "c0ffa724-9aa3-432b-8c2d-6275cb413e1d"
}
```

### 证据 2: 等待工具状态 ACTIVE

```
{
  "Status": "ACTIVE",
  "StatusReason": "",
  "ImageDigest": "sha256:21b067114e8615b607b7b377e7a2e5ef8e6160c6525059f1d9628a9ec637003a"
}
```

### 证据 4: 启动沙箱实例 StartSandboxInstance

```
{
  "Instance": {
    "InstanceId": "ywelopbyczp7peanfk4wtpfam4y4g2k6smtwqjf2",
    "ToolId": "sdt-4mncnm4u",
    "ToolName": "agstest-tc01-1789801175",
    "Status": "RUNNING",
    "TimeoutSeconds": 900,
    "ExpiresAt": "2026-09-19T15:14:52+08:00",
    "Persistent": false,
    "CreateTime": "2026-09-19T14:59:56+08:00",
    "UpdateTime": "2026-09-19T14:59:56+08:00",
    "CustomConfiguration": {
      "Image": "euson-tcr.tencentcloudcr.com/sandbox/sandbox:v1",
      "ImageRegistryType": "enterprise",
      "ImageDigest": "sha256:21b067114e8615b607b7b377e7a2e5ef8e6160c6525059f1d9628a9ec637003a",
      "Command": [
        "sh"
      ],
      "Args": [
        "-c",
        "/usr/bin/envd -port 49983"
      ],
      "Ports": [
        {
          "Name": "envd",
          "Port": 49983,
          "Protocol": "TCP"
        }
      ],
      "Resources": {
        "CPU": "2000m",
        "Memory": "4096Mi",
        "Storage": "1024Mi"
      },
      "Probe": {
        "HttpGet": {
          "Path": "/health",
          "Port": 49983,
          "Scheme": "HTTP"
        },
        "ReadyTimeoutMs": 30000,
        "ProbeTimeoutMs": 2000,
        "ProbePeriodMs": 3000,
        "SuccessThreshold": 1,
        "FailureThreshold": 100
      }
    },
    "NetworkMode": "VPC",
    "AuthMode": "DEFAULT",
    "AutoPause": false,
    "AutoResume": false
  },
  "RequestId": "00af754a-6473-4d07-afd7-ab46bd4d1a3e"
}
```

### 证据 5: 等待实例状态 RUNNING

```
{
  "Status": "RUNNING",
  "NetworkMode": "VPC",
  "ExpiresAt": "2026-09-19T15:14:52+08:00",
  "StopReason": null
}
```

### 证据 7: 数据面执行 shell 命令

```
{
  "exit_code": 0,
  "stdout": "AGS-BASELINE-OK\n1024\nNAME=\"Debian GNU/Linux\"\nVERSION=\"13 (trixie)\"\n3\n               total        used        free      shared  buff/cache   available\nMem:            4984         131        4805           0          64        4853\noverlay2        1.1G   56K  1.1G   1% /\n",
  "stderr": ""
}
```

### 证据 9: VPC 出网行为记录

```
{
  "exit": 0,
  "out": "200",
  "err": ""
}
```

### 证据 10: 停止实例并确认回收

```
{
  "duration": 0.5291628837585449
}
```

## 备注

- VPC 模式通常无公网出口（除非子网挂 NAT）；该步骤只记录行为，不作断言

## 附件

- `/root/ags/reports/artifacts/TC-01-tool-request.json` — tool-request
- `/root/ags/reports/artifacts/TC-01-shell-output.txt` — shell-output
