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
