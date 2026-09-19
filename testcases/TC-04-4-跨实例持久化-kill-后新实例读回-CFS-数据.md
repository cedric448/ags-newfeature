# TC-04-4 跨实例持久化：kill 后新实例读回 CFS 数据

| 项 | 值 |
|---|---|
| 结论 | **PASS** |
| 执行时间 | 2026-09-19 15:08:54 |
| 耗时 | 45.8s |
| 网络模式 | VPC |

## 测试目的

kill 当前实例，启动一个全新实例挂载同一 CFS（同 FileSystemId + Path），验证数据仍可读。

## 前置条件

TC-04-3 已写入数据

## 测试步骤与结果

| # | 步骤 | 结论 | 耗时 | 说明 |
|---|------|------|------|------|
| 1 | 两次实例 sandbox_id 不同 | ✅ PASS | 0.0s | yxc3p7cio7y7ppqnv3jysnhka4f422hpoxbaysn6 != 6ztuqg3axfxpowr6ahrv4lhowv6mqmyjcisbswtl |
| 2 | 新实例读回 CFS 数据 | ✅ PASS | 0.0s | 读到 cfs-payload-1789801669 |
