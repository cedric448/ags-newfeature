# TC-02-5 跨实例持久化：kill 后新实例可读回数据

| 项 | 值 |
|---|---|
| 结论 | **PASS** |
| 执行时间 | 2026-09-19 15:25:47 |
| 耗时 | 9.5s |
| 网络模式 | VPC |

## 测试目的

kill 第一个实例，启动全新实例（同 StorageMount.Name + 同 subPath），验证数据由 AgentBucket 持久化、不依赖单实例生命周期。

## 前置条件

TC-02-4 已成功写入数据

## 测试步骤与结果

| # | 步骤 | 结论 | 耗时 | 说明 |
|---|------|------|------|------|
| 1 | 两次实例 sandbox_id 不同 | ✅ PASS | 0.0s | mdhc5wdcgoz7pd2x6osbg6gxlquirqx7jyrkwaff != vu7ptfli2qjf35g6yrm5owp6st34t3t2pjctb7yt |
| 2 | 新实例读回 AgentBucket 数据 | ✅ PASS | 0.0s | 读到 agentbucket-payload-1789802720 |
