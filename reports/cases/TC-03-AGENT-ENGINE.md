# 测试报告：TC-03 Agent Engine 弹性部署（region=ap-shanghai）

生成时间：2026-09-19 15:01:43　总耗时：93.6s

## 汇总

| 结论 | 数量 |
|---|---|
| PASS | 9 |

| 用例 | 标题 | 结论 | 通过/失败 | 耗时 |
|---|---|---|---|---|
| TC-03-1 | Deployment 接口地域支持性探测 | PASS | 3/0 | 93.6s |
| TC-03-2 | 创建 Persistent 工具（含类型约束负例） | PASS | 3/0 | 93.1s |
| TC-03-3 | 创建 Deployment 并等待 ACTIVE | PASS | 5/0 | 86.4s |
| TC-03-4 | 获取 Deployment Token 并访问数据面 | PASS | 4/0 | 86.1s |
| TC-03-4b | 弹性部署按需拉起沙箱实例 | PASS | 1/0 | 81.2s |
| TC-03-5 | ModifyDeployment 修改伸缩与生命周期配置 | PASS | 3/0 | 81.0s |
| TC-03-6 | DescribeDeployment / DescribeDeploymentList 查询 | PASS | 2/0 | 77.7s |
| TC-03-7 | 负例：绑定非 Persistent 工具应被拒 | PASS | 1/0 | 77.4s |
| TC-03-8 | 删除 Deployment（异步）+ 同名资源占用 | PASS | 2/0 | 77.1s |

---

# TC-03-1 Deployment 接口地域支持性探测

| 项 | 值 |
|---|---|
| 结论 | **PASS** |
| 执行时间 | 2026-09-19 15:00:10 |
| 耗时 | 93.6s |

## 测试目的

确认 Deployment 系列接口在哪些地域可用。文档声明仅 ap-chongqing / ap-hongkong / ap-shanghai。

## 前置条件

腾讯云凭据可用

## 测试步骤与结果

| # | 步骤 | 结论 | 耗时 | 说明 |
|---|------|------|------|------|
| 1 | 地域探测完成 | ✅ PASS | 0.0s | ap-shanghai 为目标地域 |
| 2 | 目标地域可用 | ✅ PASS | 0.0s | ap-shanghai 支持 Deployment |
| 3 | 北京地域不支持（预期行为，记录用） | ✅ PASS | 0.0s | ap-beijing 返回 UnsupportedRegion |

### 证据 1: 地域探测完成

```
{
  "ap-shanghai": "SUPPORTED",
  "ap-hongkong": "SUPPORTED",
  "ap-chongqing": "SUPPORTED",
  "ap-beijing": "UNSUPPORTED",
  "ap-guangzhou": "UNSUPPORTED",
  "ap-singapore": "UNSUPPORTED"
}
```

---

# TC-03-2 创建 Persistent 工具（含类型约束负例）

| 项 | 值 |
|---|---|
| 结论 | **PASS** |
| 执行时间 | 2026-09-19 15:00:10 |
| 耗时 | 93.1s |

## 测试目的

Deployment 必须绑定 Persistent=true 的工具；验证 Persistent 的类型限制：仅 custom/mobile/android-world/osworld/waa 支持，code-interpreter 应被拒。

## 前置条件

镜像 ccr.ccs.tencentyun.com/ags.dev/go-httpbin:v2.25.0 在 ap-shanghai 可拉取

## 测试步骤与结果

| # | 步骤 | 结论 | 耗时 | 说明 |
|---|------|------|------|------|
| 1 | code-interpreter 不支持 Persistent | ✅ PASS | 0.0s | 拒绝符合预期 |
| 2 | 创建 custom Persistent 工具 | ✅ PASS | 0.0s | ToolId=sdt-q3df21oo |
| 3 | 工具 Persistent=true | ✅ PASS | 0.0s | Persistent=True |

### 证据 1: code-interpreter 不支持 Persistent

```
[InvalidParameter] [TencentCloudSDKException] code:InvalidParameter message:persistent mode is only supported for custom, mobile, android-world, osworld and waa tool types, got code-interpreter requestId:b522f4f3-c4da-447b-b614-6fee76430de0 (RequestId: b522f4f3-c4da-447b-b614-6fee76430de0)
```

### 证据 2: 创建 custom Persistent 工具

```
{
  "ToolId": "sdt-q3df21oo",
  "RequestId": "76f8ccb6-5594-4b11-9245-92655eae61f4"
}
```

### 证据 3: 工具 Persistent=true

```
{
  "Status": "ACTIVE",
  "Persistent": true
}
```

---

# TC-03-3 创建 Deployment 并等待 ACTIVE

| 项 | 值 |
|---|---|
| 结论 | **PASS** |
| 执行时间 | 2026-09-19 15:00:17 |
| 耗时 | 86.4s |

## 测试目的

绑定 Persistent 工具创建弹性部署，验证默认值物化（伸缩 / 生命周期 / 亲和）。

## 前置条件

工具 agstest-tc03-1789801210 已 ACTIVE 且 Persistent=true

## 测试步骤与结果

| # | 步骤 | 结论 | 耗时 | 说明 |
|---|------|------|------|------|
| 1 | CreateDeployment | ✅ PASS | 0.0s | DeploymentId=dpl-mkbphi9p |
| 2 | 状态为 ACTIVE | ✅ PASS | 0.0s | Status=ACTIVE |
| 3 | 伸缩配置已物化 | ✅ PASS | 0.0s | Scaling={'MinInstanceCount': 0, 'MaxInstanceCount': 3, 'MaxInstanceRequestConcurrency': 10} |
| 4 | 生命周期配置已物化 | ✅ PASS | 0.0s | IdleAction=STOP |
| 5 | 亲和配置含 HeaderName | ✅ PASS | 0.0s | HeaderName=X-Tencent-Agr-Affinity-Id |

### 证据 1: CreateDeployment

```
{
  "Deployment": {
    "DeploymentId": "dpl-mkbphi9p",
    "DeploymentName": "agstest-dpl-1789801210",
    "ToolId": "sdt-q3df21oo",
    "ScalingConfiguration": {
      "MinInstanceCount": 0,
      "MaxInstanceCount": 3,
      "MaxInstanceRequestConcurrency": 10
    },
    "LifecycleConfiguration": {
      "IdleTimeoutSeconds": 300,
      "IdleAction": "STOP"
    },
    "AffinityConfiguration": {
      "Mode": "BEST_EFFORT",
      "HeaderName": "X-Tencent-Agr-Affinity-Id"
    },
    "Status": "ACTIVE",
    "CreatedTime": "2026-09-19T07:00:17Z",
    "UpdatedTime": "2026-09-19T07:00:17Z",
    "Tags": []
  },
  "RequestId": "75a127c9-46f4-4493-81a6-8e6883cc19f0"
}
```

## 附件

- `/root/ags/reports/artifacts/TC-03-3-create-deployment-request.json` — create-deployment-request

---

# TC-03-4 获取 Deployment Token 并访问数据面

| 项 | 值 |
|---|---|
| 结论 | **PASS** |
| 执行时间 | 2026-09-19 15:00:17 |
| 耗时 | 86.1s |

## 测试目的

通过 AcquireDeploymentToken 拿短期 Token，携带 X-Access-Token 访问 https://8080-{dpl}. ap-shanghai.tencentags.com，验证稳定入口按需拉起沙箱并返回内容。

## 前置条件

Deployment dpl-mkbphi9p 为 ACTIVE；工具容器在 8080 监听 HTTP

## 测试步骤与结果

| # | 步骤 | 结论 | 耗时 | 说明 |
|---|------|------|------|------|
| 1 | AcquireDeploymentToken | ✅ PASS | 0.0s | Token 前缀=dpt_zRbYFPUx… ExpiresAt=2026-09-20T07:00:17Z |
| 2 | 数据面返回 200 | ✅ PASS | 0.0s | HTTP 200（尝试 1 次） |
| 3 | 响应为预期的 httpbin JSON 结构 | ✅ PASS | 0.0s | 返回 httpbin 标准结构 |
| 4 | 缺少 X-Access-Token 时应被拒绝 | ✅ PASS | 0.0s | 无 Token 被拒 |

### 证据 1: AcquireDeploymentToken

```
{
  "ExpiresAt": "2026-09-20T07:00:17Z",
  "Token": "dpt_zRbYFPUx95XL696ym22on2FrCUOjHoDGUiKFfhuYny4"
}
```

### 证据 2: 数据面返回 200

```
{
  "url": "https://8080-dpl-mkbphi9p.ap-shanghai.agents.tencentags.com",
  "attempts": 1,
  "last": "HTTP 200",
  "body": "{\n  \"args\": {},\n  \"headers\": {\n    \"Accept\": [\n      \"*/*\"\n    ],\n    \"Accept-Encoding\": [\n      \"gzip, deflate\"\n    ],\n    \"B3\": [\n      \"88504daffd0416f5f44587afe703922c-f3a8a1a3cab5c1c4-1\"\n    ],\n    \"Connection\": [\n      \"upgrade\"\n    ],\n    \"Host\": [\n      \"8080-hpwj7oozi5df35vxj6mlui65twxb6nk37622icxh.ap-shanghai.internal.tencentags.com\"\n    ],\n    \"Traceparent\": [\n      \"00-88504daffd0416f5"
}
```

### 证据 3: 响应为预期的 httpbin JSON 结构

```
{
  "args": {},
  "headers": {
    "Accept": [
      "*/*"
    ],
    "Accept-Encoding": [
      "gzip, deflate"
    ],
    "B3": [
      "88504daffd0416f5f44587afe703922c-f3a8a1a3cab5c1c4-1"
    ],
    "Connection": [
      "upgrade"
    ],
    "Host": [
      "8080-hpwj7oozi5df35vxj6mlui65twxb6nk37622icxh.ap-shanghai.internal.tencentags.com"
    ],
    "Traceparent": [
      "00-88504daffd0416f5
```

### 证据 4: 缺少 X-Access-Token 时应被拒绝

```
{
  "status": 401,
  "body": "{\"code\":\"unauthenticated\",\"message\":\"authentication is required\",\"request_id\":\"QFLW5ERBQBIYSOWAUMFB657R5K\"}\n"
}
```

## 备注

- 数据面 URL: https://8080-dpl-mkbphi9p.ap-shanghai.agents.tencentags.com（HTTP 端口域名规则：{port}-{dpl-id}.{region}.agents.{data-plane-domain}）

---

# TC-03-4b 弹性部署按需拉起沙箱实例

| 项 | 值 |
|---|---|
| 结论 | **PASS** |
| 执行时间 | 2026-09-19 15:00:22 |
| 耗时 | 81.2s |

## 测试目的

数据面首次请求应触发平台自动创建沙箱实例（MinInstanceCount=0 时的 0→N 扩容），验证工具下有 RUNNING 实例。

## 前置条件

Deployment dpl-mkbphi9p 绑定的工具 sdt-q3df21oo

## 测试步骤与结果

| # | 步骤 | 结论 | 耗时 | 说明 |
|---|------|------|------|------|
| 1 | 存在由部署拉起的实例 | ✅ PASS | 0.0s | 1 个实例: ['hpwj7oozi5df35vxj6mlui65twxb6nk37622icxh'] |

### 证据 1: 存在由部署拉起的实例

```
[
  {
    "InstanceId": "hpwj7oozi5df35vxj6mlui65twxb6nk37622icxh",
    "Status": "RUNNING"
  }
]
```

---

# TC-03-5 ModifyDeployment 修改伸缩与生命周期配置

| 项 | 值 |
|---|---|
| 结论 | **PASS** |
| 执行时间 | 2026-09-19 15:00:22 |
| 耗时 | 81.0s |

## 测试目的

验证修改配置后回读一致。注意：伸缩/生命周期/亲和对象是「完整替换」语义，必须提供该对象的全部字段。

## 前置条件

Deployment dpl-mkbphi9p 为 ACTIVE

## 测试步骤与结果

| # | 步骤 | 结论 | 耗时 | 说明 |
|---|------|------|------|------|
| 1 | ModifyDeployment 调用成功 | ✅ PASS | 0.0s |  |
| 2 | 伸缩配置已更新 | ✅ PASS | 0.0s | Scaling={'MinInstanceCount': 1, 'MaxInstanceCount': 5, 'MaxInstanceRequestConcurrency': 20} |
| 3 | 生命周期配置已更新 | ✅ PASS | 0.0s | IdleAction=PAUSE |

### 证据 1: ModifyDeployment 调用成功

```
{
  "Deployment": {
    "DeploymentId": "dpl-mkbphi9p",
    "DeploymentName": "agstest-dpl-1789801210",
    "ToolId": "sdt-q3df21oo",
    "ScalingConfiguration": {
      "MinInstanceCount": 1,
      "MaxInstanceCount": 5,
      "MaxInstanceRequestConcurrency": 20
    },
    "LifecycleConfiguration": {
      "IdleTimeoutSeconds": 600,
      "IdleAction": "PAUSE"
    },
    "AffinityConfiguration": {
      "Mode": "BEST_EFFORT",
      "HeaderName": "X-Tencent-Agr-Affinity-Id"
    },
    "Status": "ACTIVE",
    "CreatedTime": "2026-09-19T07:00:17Z",
    "UpdatedTime": "2026-09-19T07:00:22Z",
    "Tags": []
  },
  "RequestId": "0dcda136-0af3-4f8d-a3dc-50f1035e0daa"
}
```

---

# TC-03-6 DescribeDeployment / DescribeDeploymentList 查询

| 项 | 值 |
|---|---|
| 结论 | **PASS** |
| 执行时间 | 2026-09-19 15:00:25 |
| 耗时 | 77.7s |

## 测试目的

验证按 ID 单查与列表查询都能命中刚创建的 Deployment。

## 前置条件

Deployment dpl-mkbphi9p 存在

## 测试步骤与结果

| # | 步骤 | 结论 | 耗时 | 说明 |
|---|------|------|------|------|
| 1 | DescribeDeployment 命中 | ✅ PASS | 0.0s | Name=agstest-dpl-1789801210 |
| 2 | DescribeDeploymentList 命中 | ✅ PASS | 0.0s | 列表共 1 条 |

### 证据 1: DescribeDeployment 命中

```
{
  "DeploymentId": "dpl-mkbphi9p",
  "DeploymentName": "agstest-dpl-1789801210",
  "ToolId": "sdt-q3df21oo",
  "ScalingConfiguration": {
    "MinInstanceCount": 1,
    "MaxInstanceCount": 5,
    "MaxInstanceRequestConcurrency": 20
  },
  "LifecycleConfiguration": {
    "IdleTimeoutSeconds": 600,
    "IdleAction": "PAUSE"
  },
  "AffinityConfiguration": {
    "Mode": "BEST_EFFORT",
    "HeaderName": "X-Tencent-Agr-Affinity-Id"
  },
  "Status": "ACTIVE",
  "CreatedTime": "2026-09-19T07:00:17Z",
  "UpdatedTime": "2026-09-19T07:00:22Z",
  "Tags": []
}
```

### 证据 2: DescribeDeploymentList 命中

```
[
  "dpl-mkbphi9p"
]
```

---

# TC-03-7 负例：绑定非 Persistent 工具应被拒

| 项 | 值 |
|---|---|
| 结论 | **PASS** |
| 执行时间 | 2026-09-19 15:00:26 |
| 耗时 | 77.4s |

## 测试目的

文档要求绑定的工具必须 Persistent=true。用已有非 Persistent 工具（如 code-interpreter）创建 Deployment 应报错。

## 前置条件

存在非 Persistent 的工具

## 测试步骤与结果

| # | 步骤 | 结论 | 耗时 | 说明 |
|---|------|------|------|------|
| 1 | 非 Persistent 工具被拒 | ✅ PASS | 0.0s | 拒绝符合预期 |

### 证据 1: 非 Persistent 工具被拒

```
[UnsupportedOperation.SandboxTool] [TencentCloudSDKException] code:UnsupportedOperation.SandboxTool message:UnsupportedOperation.SandboxTool: SandboxTool must be persistent requestId:4f6e660a-0a77-46ef-95b2-0ee97b9f3bad (RequestId: 4f6e660a-0a77-46ef-95b2-0ee97b9f3bad)
```

---

# TC-03-8 删除 Deployment（异步）+ 同名资源占用

| 项 | 值 |
|---|---|
| 结论 | **PASS** |
| 执行时间 | 2026-09-19 15:00:26 |
| 耗时 | 77.1s |

## 测试目的

验证删除是异步操作、需轮询最终状态；删除后同名才可复用。

## 前置条件

Deployment dpl-mkbphi9p 存在

## 测试步骤与结果

| # | 步骤 | 结论 | 耗时 | 说明 |
|---|------|------|------|------|
| 1 | DeleteDeployment 调用成功 | ✅ PASS | 0.0s |  |
| 2 | 删除最终生效 | ✅ PASS | 0.0s | 资源已不可查/已删除 |

### 证据 1: DeleteDeployment 调用成功

```
{
  "RequestId": "e145d7ac-c0eb-4987-8ecc-9602c83430ed"
}
```

### 证据 2: 删除最终生效

```
{
  "final": "GONE"
}
```
