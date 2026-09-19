# TC-04-5 同一 CFS 不同 subPath → 目录隔离

| 项 | 值 |
|---|---|
| 结论 | **PASS** |
| 执行时间 | 2026-09-19 15:31:10 |
| 耗时 | 47.2s |
| 网络模式 | VPC |

## 测试目的

同一工具、同一 StorageMount.Name，通过 MountOptions.SubPath 指定子目录，应映射到 CFS 内的不同目录，互相看不到数据。

## 前置条件

TC-04-4 已在根目录写入数据

## 测试步骤与结果

| # | 步骤 | 结论 | 耗时 | 说明 |
|---|------|------|------|------|
| 1 | 带 MountOptions.SubPath 启动实例 | ✅ PASS | 0.0s | InstanceId=ufcrrosj4f2kezxbztg6bh7eyqio3omceyjn6u7b |
| 2 | 不同 subPath 看不到原目录数据 | ✅ PASS | 0.0s | 隔离生效 |

### 证据 1: 带 MountOptions.SubPath 启动实例

```
{
  "MountOptions": [
    {
      "Name": "cfs-workspace",
      "MountPath": "/mnt/cfs-alt",
      "SubPath": "iso-1789803009"
    }
  ]
}
```

### 证据 2: 不同 subPath 看不到原目录数据

```
{
  "stdout": "ls: cannot open directory '/mnt/cfs-alt': No such file or directory\nNOT-FOUND\n",
  "stderr": ""
}
```
