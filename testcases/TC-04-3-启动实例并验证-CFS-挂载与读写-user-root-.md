# TC-04-3 启动实例并验证 CFS 挂载与读写（user=root）

| 项 | 值 |
|---|---|
| 结论 | **PASS** |
| 执行时间 | 2026-09-19 15:38:50 |
| 耗时 | 61.8s |
| 网络模式 | VPC |
| 被测镜像 | `euson-tcr.tencentcloudcr.com/sandbox/sandbox:v1` |

## 测试目的

启动实例，确认 /mnt/cfs 已挂载为 CFS，并以 root 身份完成目录创建与文件读写。

## 前置条件

工具 agstest-tc04-1789803489 已 ACTIVE

## 测试步骤与结果

| # | 步骤 | 结论 | 耗时 | 说明 |
|---|------|------|------|------|
| 1 | 启动实例并 RUNNING | ✅ PASS | 0.0s | InstanceId=evrkzwaeniff3msw4txg43ipqivei5grbvh4m2ys |
| 2 | E2B 连接实例 | ✅ PASS | 0.0s | sandbox_id=z4zkntm76bf7pavnyqphlaxbfgxdobwa6go2hqwz |
| 3 | CFS 已挂载且可创建目录并写入 | ✅ PASS | 0.0s | 挂载与读写均成功 |
| 4 | 非 root 用户访问受限（记录用） | ✅ PASS | 0.0s | 已用 user=root 验证 |

### 证据 1: 启动实例并 RUNNING

```
{
  "Status": "RUNNING",
  "NetworkMode": "VPC"
}
```

### 证据 3: CFS 已挂载且可创建目录并写入

```
{
  "stdout": "--- mount ---\nvirtio_rw_44e51c2a on /mnt/cfs type virtiofs (rw,relatime)\n--- df ---\nFilesystem         Type      Size  Used Avail Use% Mounted on\nvirtio_rw_44e51c2a virtiofs  500M  129M  372M  26% /mnt/cfs\n--- fs type 校验 ---\nfuse\n--- write ---\ncfs-payload-1789803489\n",
  "stderr": ""
}
```

## 备注

- 官方文档明确：沙箱内访问 CFS 挂载点须指定 user="root"，否则权限不足

## 附件

- `/root/ags/reports/artifacts/TC-04-3-cfs-mount-check.txt` — cfs-mount-check
