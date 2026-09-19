# TC-02-4 E2B 文件 API 读写挂载目录（write/read/list/exists）

| 项 | 值 |
|---|---|
| 结论 | **PASS** |
| 执行时间 | 2026-09-19 15:25:45 |
| 耗时 | 10.9s |
| 网络模式 | VPC |

## 测试目的

验证 files.write / files.read / files.list / files.exists 在 AgentBucket 挂载目录上均可用。

## 前置条件

实例已挂载 AgentBucket

## 测试步骤与结果

| # | 步骤 | 结论 | 耗时 | 说明 |
|---|------|------|------|------|
| 1 | files.write 写入 | ✅ PASS | 0.0s | /mnt/data/agentbucket-alt/agstest/file-api.txt |
| 2 | files.read 读回一致 | ✅ PASS | 0.0s | 内容一致 |
| 3 | files.exists 返回 True | ✅ PASS | 0.0s | 存在 |
| 4 | files.list 能列出目录内容 | ✅ PASS | 0.0s | 条目=['file-api.txt', 'probe.txt'] |
