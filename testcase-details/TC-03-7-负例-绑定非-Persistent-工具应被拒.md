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
