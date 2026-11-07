# 测试报告：TC-02 AgentBucket 持久化存储

生成时间：2026-09-19 15:41:24　总耗时：30.0s

## 汇总

| 结论 | 数量 |
|---|---|
| PASS | 8 |

| 用例 | 标题 | 结论 | 通过/失败 | 耗时 |
|---|---|---|---|---|
| TC-02-1 | 创建带 AgentBucket 的 code-interpreter 工具 | PASS | 4/0 | 30.0s |
| TC-02-2 | 负例：custom 工具缺 Probe 应报 MissingParameter | PASS | 1/0 | 12.6s |
| TC-02-3 | E2B 启动实例并通过 x-mounts[].subPath 指定 spaceID | PASS | 2/0 | 12.6s |
| TC-02-4 | E2B 文件 API 读写挂载目录（write/read/list/exists） | PASS | 4/0 | 10.1s |
| TC-02-5 | 跨实例持久化：kill 后新实例可读回数据 | PASS | 2/0 | 8.8s |
| TC-02-6 | 同一工具不同 subPath 数据空间隔离 | PASS | 1/0 | 2.6s |
| TC-02-7 | 实例级只读收紧：readOnly=true 后写入被拒 | PASS | 1/0 | 1.9s |
| TC-02-8 | 负例：不存在的 spaceID 挂载行为 | PASS | 2/0 | 0.6s |

---

# TC-02-1 创建带 AgentBucket 的 code-interpreter 工具

| 项 | 值 |
|---|---|
| 结论 | **PASS** |
| 执行时间 | 2026-09-19 15:40:54 |
| 耗时 | 30.0s |
| 网络模式 | VPC |

## 测试目的

验证按 E2B subPath=spaceID 模式创建工具：只传 LibraryId、不传 SpaceId，工具应变为 ACTIVE 且回查 LibraryId 一致。

## 前置条件

SMH LibraryId=smh3qv6cmcoscm4i；spaceID=space3ly9r9ni7fhju；RoleArn 具备 QcloudSMHFullAccess；VPC=vpc-ovochv3a

## 测试步骤与结果

| # | 步骤 | 结论 | 耗时 | 说明 |
|---|------|------|------|------|
| 1 | CreateSandboxTool (code-interpreter) | ✅ PASS | 0.0s | ToolId=sdt-9nnj4qug |
| 2 | 等待工具 ACTIVE | ✅ PASS | 0.0s | Status=ACTIVE |
| 3 | 回查 LibraryId 与请求一致 | ✅ PASS | 0.0s | LibraryId=smh3qv6cmcoscm4i |
| 4 | 创建工具阶段未回填 SpaceId | ✅ PASS | 0.0s | 确认未传 SpaceId |

### 证据 1: CreateSandboxTool (code-interpreter)

```
{
  "ToolId": "sdt-9nnj4qug",
  "RequestId": "e4562a08-9831-4712-a618-5e7190dc76d5"
}
```

### 证据 3: 回查 LibraryId 与请求一致

```
[
  {
    "Name": "agentbucket",
    "StorageSource": {
      "AgentBucket": {
        "LibraryId": "smh3qv6cmcoscm4i",
        "AccessDomain": "smh3qv6cmcoscm4i.ap-beijing.api.tencentsmh.cn"
      }
    },
    "MountPath": "/mnt/data/agentbucket"
  }
]
```

## 附件

- `/root/ags/reports/artifacts/TC-02-1-tool-request.json` — tool-request

---

# TC-02-2 负例：custom 工具缺 Probe 应报 MissingParameter

| 项 | 值 |
|---|---|
| 结论 | **PASS** |
| 执行时间 | 2026-09-19 15:41:11 |
| 耗时 | 12.6s |
| 网络模式 | VPC |
| 被测镜像 | `euson-tcr.tencentcloudcr.com/cedricbwang/test:v1` |

## 测试目的

验证 CustomConfiguration.Probe 为必填，缺失时云 API 返回 MissingParameter.CustomConfiguration.Probe。

## 前置条件

同 TC-02-1

## 测试步骤与结果

| # | 步骤 | 结论 | 耗时 | 说明 |
|---|------|------|------|------|
| 1 | 返回 MissingParameter 类错误 | ✅ PASS | 0.0s | 错误符合预期 |

### 证据 1: 返回 MissingParameter 类错误

```
[MissingParameter] [TencentCloudSDKException] code:MissingParameter message:CustomConfiguration.Probe is required requestId:51865c8a-1d0b-4e2f-ab58-2232d0ce46ca (RequestId: 51865c8a-1d0b-4e2f-ab58-2232d0ce46ca)
```

---

# TC-02-3 E2B 启动实例并通过 x-mounts[].subPath 指定 spaceID

| 项 | 值 |
|---|---|
| 结论 | **PASS** |
| 执行时间 | 2026-09-19 15:41:11 |
| 耗时 | 12.6s |
| 网络模式 | VPC |
| 被测镜像 | `euson-tcr.tencentcloudcr.com/cedricbwang/test:v1` |

## 测试目的

验证 metadata.x-mounts[].subPath 传 spaceID、mountPath 覆盖工具级默认值（/mnt/data/agentbucket → /mnt/data/agentbucket-alt）。

## 前置条件

工具 agstest-tc02-1789803654 已 ACTIVE；spaceID=space3ly9r9ni7fhju

## 测试步骤与结果

| # | 步骤 | 结论 | 耗时 | 说明 |
|---|------|------|------|------|
| 1 | E2B 创建沙箱实例 | ✅ PASS | 0.0s | sandbox_id=j2ajv7goy3fqqmckcheazmesffnr3cq5klpe5ghm |
| 2 | 挂载点存在且可创建目录并写入 | ✅ PASS | 0.0s | exit=0，写入成功 |

### 证据 2: 挂载点存在且可创建目录并写入

```
{
  "stdout": "--- mount listing ---\nvirtio_rw_44e51c2a on /mnt/data/agentbucket-alt type virtiofs (rw,relatime)\n--- df ---\nFilesystem         Type      Size  Used Avail Use% Mounted on\nvirtio_rw_44e51c2a virtiofs  500M  113M  388M  23% /mnt/data/agentbucket-alt\n--- mkdir+write ---\nhello-bucket\n",
  "stderr": ""
}
```

---

# TC-02-4 E2B 文件 API 读写挂载目录（write/read/list/exists）

| 项 | 值 |
|---|---|
| 结论 | **PASS** |
| 执行时间 | 2026-09-19 15:41:14 |
| 耗时 | 10.1s |
| 网络模式 | VPC |
| 被测镜像 | `euson-tcr.tencentcloudcr.com/cedricbwang/test:v1` |

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

---

# TC-02-5 跨实例持久化：kill 后新实例可读回数据

| 项 | 值 |
|---|---|
| 结论 | **PASS** |
| 执行时间 | 2026-09-19 15:41:15 |
| 耗时 | 8.8s |
| 网络模式 | VPC |
| 被测镜像 | `euson-tcr.tencentcloudcr.com/cedricbwang/test:v1` |

## 测试目的

kill 第一个实例，启动全新实例（同 StorageMount.Name + 同 subPath），验证数据由 AgentBucket 持久化、不依赖单实例生命周期。

## 前置条件

TC-02-4 已成功写入数据

## 测试步骤与结果

| # | 步骤 | 结论 | 耗时 | 说明 |
|---|------|------|------|------|
| 1 | 两次实例 sandbox_id 不同 | ✅ PASS | 0.0s | j2ajv7goy3fqqmckcheazmesffnr3cq5klpe5ghm != wugtvw7lirikfbfaqxna2xk5th3lt5fmov6zre24 |
| 2 | 新实例读回 AgentBucket 数据 | ✅ PASS | 0.0s | 读到 agentbucket-payload-1789803654 |

---

# TC-02-6 同一工具不同 subPath 数据空间隔离

| 项 | 值 |
|---|---|
| 结论 | **PASS** |
| 执行时间 | 2026-09-19 15:41:21 |
| 耗时 | 2.6s |
| 网络模式 | VPC |
| 被测镜像 | `euson-tcr.tencentcloudcr.com/cedricbwang/test:v1` |

## 测试目的

同一工具、同一 StorageMount.Name，换一个 subPath 启动实例，应看不到 TC-02-5 写入的文件。

## 前置条件

TC-02-5 已在 spaceID A 写入数据

## 测试步骤与结果

| # | 步骤 | 结论 | 耗时 | 说明 |
|---|------|------|------|------|
| 1 | 不同 subPath 看不到原空间数据 | ✅ PASS | 0.0s | 隔离生效（space=space3ly9r9ni7fhju-alt） |

### 证据 1: 不同 subPath 看不到原空间数据

```
{
  "stdout": "ls: cannot access '/mnt/data/agentbucket-alt/agstest': No such file or directory\n=== exists check ===\nNOT-FOUND\n",
  "stderr": ""
}
```

---

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

---

# TC-02-8 负例：不存在的 spaceID 挂载行为

| 项 | 值 |
|---|---|
| 结论 | **PASS** |
| 执行时间 | 2026-09-19 15:41:23 |
| 耗时 | 0.6s |
| 网络模式 | VPC |
| 被测镜像 | `euson-tcr.tencentcloudcr.com/cedricbwang/test:v1` |

## 测试目的

文档说明：传入不存在的 spaceID 时实例仍可启动，但挂载目录不会被创建/访问报 no such file or directory。

## 前置条件

同 TC-02-3

## 测试步骤与结果

| # | 步骤 | 结论 | 耗时 | 说明 |
|---|------|------|------|------|
| 1 | 实例仍能启动 | ✅ PASS | 0.0s | sandbox_id=mj5h42h5mfskfz6547zp5fce2p6xwbkelfdkfwyt |
| 2 | 记录挂载目录访问结果 | ✅ PASS | 0.0s | exit=0 |

### 证据 2: 记录挂载目录访问结果

```
{
  "stdout": "ls: cannot open directory '/mnt/data/agentbucket-alt': No such file or directory\n",
  "stderr": ""
}
```

## 备注

- 按文档预期应报 no such file or directory；此处仅记录实际行为，不作强断言
