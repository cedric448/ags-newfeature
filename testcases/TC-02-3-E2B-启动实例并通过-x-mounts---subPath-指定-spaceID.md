# TC-02-3 E2B 启动实例并通过 x-mounts[].subPath 指定 spaceID

| 项 | 值 |
|---|---|
| 结论 | **PASS** |
| 执行时间 | 2026-09-19 15:25:42 |
| 耗时 | 13.9s |
| 网络模式 | VPC |

## 测试目的

验证 metadata.x-mounts[].subPath 传 spaceID、mountPath 覆盖工具级默认值（/mnt/data/agentbucket → /mnt/data/agentbucket-alt）。

## 前置条件

工具 agstest-tc02-1789802720 已 ACTIVE；spaceID=space3ly9r9ni7fhju

## 测试步骤与结果

| # | 步骤 | 结论 | 耗时 | 说明 |
|---|------|------|------|------|
| 1 | E2B 创建沙箱实例 | ✅ PASS | 0.0s | sandbox_id=mdhc5wdcgoz7pd2x6osbg6gxlquirqx7jyrkwaff |
| 2 | 挂载点存在且可创建目录并写入 | ✅ PASS | 0.0s | exit=0，写入成功 |

### 证据 2: 挂载点存在且可创建目录并写入

```
{
  "stdout": "--- mount listing ---\nvirtio_rw_44e51c2a on /mnt/data/agentbucket-alt type virtiofs (rw,relatime)\n--- df ---\nFilesystem         Type      Size  Used Avail Use% Mounted on\nvirtio_rw_44e51c2a virtiofs  500M  465M   36M  93% /mnt/data/agentbucket-alt\n--- mkdir+write ---\nhello-bucket\n",
  "stderr": ""
}
```
