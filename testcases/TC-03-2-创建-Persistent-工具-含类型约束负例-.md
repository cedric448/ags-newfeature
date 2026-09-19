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
