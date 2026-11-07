# TC-04-6 实例级只读收紧：readOnly=true 后写入被拒

| 项 | 值 |
|---|---|
| 结论 | **FAIL** |
| 执行时间 | 2026-09-19 15:39:14 |
| 耗时 | 37.7s |
| 网络模式 | VPC |
| 被测镜像 | `euson-tcr.tencentcloudcr.com/sandbox/sandbox:v1` |

## 测试目的

工具级可写的前提下，实例级 MountOptions.ReadOnly=true 应把挂载收紧为只读。文档明确声明「实例级可以把可写挂载收紧为只读」。

## 前置条件

工具级 StorageMount.ReadOnly=false

## 测试步骤与结果

| # | 步骤 | 结论 | 耗时 | 说明 |
|---|------|------|------|------|
| 1 | 控制面已接受 ReadOnly=true | ✅ PASS | 0.0s | MountOptions 回读=[{'Name': 'cfs-workspace', 'MountPath': '/mnt/cfs', 'ReadOnly': True}] |
| 2 | 只读挂载写入被拒 | ❌ FAIL | 0.0s | 未生效：挂载仍为读写（(rw,)=True），写入成功=True |

### 证据 1: 控制面已接受 ReadOnly=true

```
[
  {
    "Name": "cfs-workspace",
    "MountPath": "/mnt/cfs",
    "ReadOnly": true
  }
]
```

### 证据 2: 只读挂载写入被拒

```
{
  "stdout": "--- mount opts ---\nvirtio_rw_44e51c2a on /mnt/cfs type virtiofs (rw,relatime)\n--- write attempt ---\nWRITE-OK\n",
  "stderr": "",
  "exit": 0,
  "mount_options": [
    {
      "Name": "cfs-workspace",
      "MountPath": "/mnt/cfs",
      "ReadOnly": true
    }
  ]
}
```

## 备注

- 【缺陷】实例级 MountOptions.ReadOnly=true 被控制面接受并原样回读，但在沙箱内挂载仍为 rw（virtiofs），写入成功，只读收紧未生效。对比：AgentBucket（TC-02-7）的同名能力工作正常，因此问题定位在 CFS 挂载路径。
