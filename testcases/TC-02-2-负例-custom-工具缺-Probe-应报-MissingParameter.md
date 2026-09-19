# TC-02-2 负例：custom 工具缺 Probe 应报 MissingParameter

| 项 | 值 |
|---|---|
| 结论 | **PASS** |
| 执行时间 | 2026-09-19 15:25:42 |
| 耗时 | 13.9s |
| 网络模式 | VPC |

## 测试目的

验证 CustomConfiguration.Probe 为必填，缺失时云 API 返回 MissingParameter.CustomConfiguration.Probe。

## 前置条件

同 TC-02-1

## 测试步骤与结果

| # | 步骤 | 结论 | 耗时 | 说明 |
|---|------|------|------|------|
| 1 | 返回 MissingParameter 类错误 | ✅ PASS | 0.0s | 错误符合预期 |

### 证据 1: 返回 MissingParameter 类错误

```
[MissingParameter] [TencentCloudSDKException] code:MissingParameter message:CustomConfiguration.Probe is required requestId:bbcf18b7-d1b4-4d44-b85c-434faa187855 (RequestId: bbcf18b7-d1b4-4d44-b85c-434faa187855)
```
