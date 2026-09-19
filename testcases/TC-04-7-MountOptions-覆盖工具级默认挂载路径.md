# TC-04-7 MountOptions 覆盖工具级默认挂载路径

| 项 | 值 |
|---|---|
| 结论 | **PASS** |
| 执行时间 | 2026-09-19 15:09:35 |
| 耗时 | 4.8s |
| 网络模式 | VPC |

## 测试目的

启动实例时通过 MountOptions.MountPath 把工具级默认 /mnt/cfs 覆盖为 /mnt/cfs-alt，验证实例内挂载点变更。

## 前置条件

TC-04-3 已验证工具级默认路径 /mnt/cfs

## 测试步骤与结果

| # | 步骤 | 结论 | 耗时 | 说明 |
|---|------|------|------|------|
| 1 | 带 MountPath 覆盖启动实例 | ✅ PASS | 0.0s | InstanceId=hjy3oxtk4py7pnxsad7nqvjvx6vys2twqe76vt3x |
| 2 | 覆盖后的路径可用 | ✅ PASS | 0.0s | /mnt/cfs-alt 可写 |

### 证据 1: 带 MountPath 覆盖启动实例

```
{
  "MountOptions": [
    {
      "Name": "cfs-workspace",
      "MountPath": "/mnt/cfs-alt"
    }
  ]
}
```

### 证据 2: 覆盖后的路径可用

```
{
  "stdout": "--- new path ---\nFilesystem         Type      Size  Used Avail Use% Mounted on\nvirtio_rw_44e51c2a virtiofs  500M  122M  379M  25% /mnt/cfs-alt\n--- old path ---\nls: cannot access '/mnt/cfs': No such file or directory\n--- write at new path ---\nOK\n",
  "stderr": ""
}
```
