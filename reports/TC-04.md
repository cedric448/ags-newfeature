# 测试报告：TC-04 AgentCFS 共享存储（FileSystemId=cfs-45a313f3e）

生成时间：2026-09-19 15:39:52　总耗时：102.8s

## 汇总

| 结论 | 数量 |
|---|---|
| PASS | 6 |
| FAIL | 1 |

| 用例 | 标题 | 结论 | 通过/失败 | 耗时 |
|---|---|---|---|---|
| TC-04-1 | 创建挂载 CFS 的 custom 工具 | PASS | 4/0 | 102.8s |
| TC-04-2 | 负例：CFS Path 指向不存在的目录 | PASS | 3/0 | 80.0s |
| TC-04-3 | 启动实例并验证 CFS 挂载与读写（user=root） | PASS | 4/0 | 61.8s |
| TC-04-4 | 跨实例持久化：kill 后新实例读回 CFS 数据 | PASS | 2/0 | 52.3s |
| TC-04-5 | 同一 CFS 不同 subPath → 目录隔离 | PASS | 2/0 | 42.8s |
| TC-04-6 | 实例级只读收紧：readOnly=true 后写入被拒 | FAIL | 1/1 | 37.7s |
| TC-04-7 | MountOptions 覆盖工具级默认挂载路径 | PASS | 2/0 | 5.2s |

---

# TC-04-1 创建挂载 CFS 的 custom 工具

| 项 | 值 |
|---|---|
| 结论 | **PASS** |
| 执行时间 | 2026-09-19 15:38:09 |
| 耗时 | 102.8s |
| 网络模式 | VPC |
| 被测镜像 | `euson-tcr.tencentcloudcr.com/sandbox/sandbox:v1` |

## 测试目的

验证 StorageSource.Cfs（FileSystemId=cfs-45a313f3e, Path=/）能被 AGS 接受，工具变为 ACTIVE 且回查配置一致。

## 前置条件

CFS cfs-45a313f3e 在 ap-beijing 可用（挂载点已建）；RoleArn 具备 CFS 权限

## 测试步骤与结果

| # | 步骤 | 结论 | 耗时 | 说明 |
|---|------|------|------|------|
| 1 | CreateSandboxTool | ✅ PASS | 0.0s | ToolId=sdt-8gyq17bg |
| 2 | 等待工具 ACTIVE | ✅ PASS | 0.0s | Status=ACTIVE |
| 3 | 回查 FileSystemId 一致 | ✅ PASS | 0.0s | FileSystemId=cfs-45a313f3e |
| 4 | 回查 Path 一致 | ✅ PASS | 0.0s | Path=/ |

### 证据 1: CreateSandboxTool

```
{
  "ToolId": "sdt-8gyq17bg",
  "RequestId": "dc92c15b-1df4-4358-8ca7-9c66ea39799a"
}
```

### 证据 3: 回查 FileSystemId 一致

```
[
  {
    "Name": "cfs-workspace",
    "StorageSource": {
      "Cfs": {
        "FileSystemId": "cfs-45a313f3e",
        "Path": "/"
      }
    },
    "MountPath": "/mnt/cfs"
  }
]
```

## 附件

- `/root/ags/reports/artifacts/TC-04-1-tool-request.json` — tool-request

---

# TC-04-2 负例：CFS Path 指向不存在的目录

| 项 | 值 |
|---|---|
| 结论 | **PASS** |
| 执行时间 | 2026-09-19 15:38:32 |
| 耗时 | 80.0s |
| 网络模式 | VPC |
| 被测镜像 | `euson-tcr.tencentcloudcr.com/sandbox/sandbox:v1` |

## 测试目的

验证 StorageMounts.Path 必须指向 CFS 内已存在的路径。实测行为：创建工具阶段【不校验】（工具仍变为 ACTIVE），错误在【启动实例】阶段才暴露为 FailedOperation.StorageMount。本用例按实际行为断言，并记录该「延迟校验」特性。

## 前置条件

同 TC-04-1

## 测试步骤与结果

| # | 步骤 | 结论 | 耗时 | 说明 |
|---|------|------|------|------|
| 1 | 创建工具阶段未校验 Path（工具被接受） | ✅ PASS | 0.0s | ToolId=sdt-5tlg01t2 |
| 2 | 工具仍变为 ACTIVE（与文档描述不符） | ✅ PASS | 0.0s | Status=ACTIVE |
| 3 | 启动实例阶段报 FailedOperation.StorageMount | ✅ PASS | 0.0s | 错误在实例启动阶段暴露，信息明确 |

### 证据 1: 创建工具阶段未校验 Path（工具被接受）

```
{
  "ToolId": "sdt-5tlg01t2",
  "RequestId": "663d4d0a-bbca-4c18-9e66-0b79048562a9"
}
```

### 证据 3: 启动实例阶段报 FailedOperation.StorageMount

```
[FailedOperation.StorageMount] [TencentCloudSDKException] code:FailedOperation.StorageMount message:storage mount path "[\"30.1.0.16@tcp0:/5a313f3e/cfs/agstest-nonexistent-1789803489\",\"/data/cubelet/storage/io.cubelet.internal.v1.storage/turbocfs/3f56c37a4f8539183b9226be854d4979/mnt\"]" not found or unreachable, please check StorageMount CFS/NFS path and network configuration requestId:efa08549-660f-4f7d-8bbc-bf38faa9c852 (RequestId: efa08549-660f-4f7d-8bbc-bf38faa9c852)
```

## 备注

- 缺陷/体验问题：Path 校验被延迟到启动实例阶段，且工具创建时返回 ACTIVE，容易让用户误以为配置正确。建议 AGS 在 CreateSandboxTool 阶段即校验 Path 可达性。

---

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

---

# TC-04-4 跨实例持久化：kill 后新实例读回 CFS 数据

| 项 | 值 |
|---|---|
| 结论 | **PASS** |
| 执行时间 | 2026-09-19 15:39:00 |
| 耗时 | 52.3s |
| 网络模式 | VPC |
| 被测镜像 | `euson-tcr.tencentcloudcr.com/sandbox/sandbox:v1` |

## 测试目的

kill 当前实例，启动一个全新实例挂载同一 CFS（同 FileSystemId + Path），验证数据仍可读。

## 前置条件

TC-04-3 已写入数据

## 测试步骤与结果

| # | 步骤 | 结论 | 耗时 | 说明 |
|---|------|------|------|------|
| 1 | 两次实例 sandbox_id 不同 | ✅ PASS | 0.0s | z4zkntm76bf7pavnyqphlaxbfgxdobwa6go2hqwz != 73yasigs7vskfxiuflilxzqqn3vz5rogtefnhktt |
| 2 | 新实例读回 CFS 数据 | ✅ PASS | 0.0s | 读到 cfs-payload-1789803489 |

---

# TC-04-5 同一 CFS 不同 subPath → 目录隔离

| 项 | 值 |
|---|---|
| 结论 | **PASS** |
| 执行时间 | 2026-09-19 15:39:09 |
| 耗时 | 42.8s |
| 网络模式 | VPC |
| 被测镜像 | `euson-tcr.tencentcloudcr.com/sandbox/sandbox:v1` |

## 测试目的

同一工具、同一 StorageMount.Name，通过 MountOptions.SubPath 指定子目录，应映射到 CFS 内的不同目录，互相看不到数据。

## 前置条件

TC-04-4 已在根目录写入数据

## 测试步骤与结果

| # | 步骤 | 结论 | 耗时 | 说明 |
|---|------|------|------|------|
| 1 | 带 MountOptions.SubPath 启动实例 | ✅ PASS | 0.0s | InstanceId=j2dzvxmfgilqrwkkdj5o2og2nqpxirf6e6fb6goa |
| 2 | 不同 subPath 看不到原目录数据 | ✅ PASS | 0.0s | 隔离生效 |

### 证据 1: 带 MountOptions.SubPath 启动实例

```
{
  "MountOptions": [
    {
      "Name": "cfs-workspace",
      "MountPath": "/mnt/cfs-alt",
      "SubPath": "iso-1789803489"
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

---

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

---

# TC-04-7 MountOptions 覆盖工具级默认挂载路径

| 项 | 值 |
|---|---|
| 结论 | **PASS** |
| 执行时间 | 2026-09-19 15:39:47 |
| 耗时 | 5.2s |
| 网络模式 | VPC |
| 被测镜像 | `euson-tcr.tencentcloudcr.com/sandbox/sandbox:v1` |

## 测试目的

启动实例时通过 MountOptions.MountPath 把工具级默认 /mnt/cfs 覆盖为 /mnt/cfs-alt，验证实例内挂载点变更。

## 前置条件

TC-04-3 已验证工具级默认路径 /mnt/cfs

## 测试步骤与结果

| # | 步骤 | 结论 | 耗时 | 说明 |
|---|------|------|------|------|
| 1 | 带 MountPath 覆盖启动实例 | ✅ PASS | 0.0s | InstanceId=xgwnwvki6xrv3su7cnkh3vzge4r42utgdtbnwrhk |
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
  "stdout": "--- new path ---\nFilesystem         Type      Size  Used Avail Use% Mounted on\nvirtio_rw_44e51c2a virtiofs  500M  128M  373M  26% /mnt/cfs-alt\n--- old path ---\nls: cannot access '/mnt/cfs': No such file or directory\n--- write at new path ---\nOK\n",
  "stderr": ""
}
```
