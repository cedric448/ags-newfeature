# TC-02-7 实例级只读收紧：readOnly=true 后写入被拒

| 项 | 值 |
|---|---|
| 结论 | **PASS** |
| 执行时间 | 2026-09-19 15:41:22 |
| 耗时 | 2.0s |
| 网络模式 | VPC |
| 被测镜像 | `euson-tcr.tencentcloudcr.com/cedricbwang/test:v1` |

## 测试目的

工具级可写的前提下，实例级 metadata.x-mounts[].readOnly=true 应把挂载收紧为只读，写入失败。

## 前置条件

工具级 StorageMount 未设置 ReadOnly

## 测试步骤与结果

| # | 步骤 | 结论 | 耗时 | 说明 |
|---|------|------|------|------|
| 1 | 只读挂载写入被拒 | ✅ PASS | 0.0s | 写入被正确拒绝 |

### 证据 1: 只读挂载写入被拒

```
{
  "stdout": "WRITE-DENIED\ntotal 1\n-rwxrwxrwx 1 root root 30 Sep 19 07:41 file-api.txt\n-rwxrwxrwx 1 root root 13 Sep 19 07:41 probe.txt\n",
  "stderr": "/bin/bash: line 1: /mnt/data/agentbucket-alt/agstest/ro-should-fail.txt: Read-only file system\n",
  "exit": 0
}
```
