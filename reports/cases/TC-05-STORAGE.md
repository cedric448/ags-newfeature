# AGS 存储模板（VolumeTemplate）挂载与读写性能测试

| 项 | 值 |
|---|---|
| 被测产品 | 腾讯云 Agent Runtime / Agent Sandbox (AGS)，API `2025-09-20` |
| 地域 | `ap-beijing` |
| 测试日期 | 2026-11-05 |
| 镜像 | `euson-tcr.tencentcloudcr.com/sandbox/sandbox:v1` |
| 网络模式 | `SANDBOX`（沙箱内网，仅隔离环境） |
| 资源规格 | 4C / 8Gi |
| 工具名 | `agstest-vt-*`（测后已回收） |
| CBS 数据卷 | `vol-01a1aa5d-...`（`cedricbwang-cbs-bench`，20Gi，Retain，测后保留） |

> **修订记录**：初版报告曾把 AgentCBS 判为「产品不支持」，复查 [docs/references/agscbs-disk.md](../../docs/references/agscbs-disk.md) / [agscbs-sys.md](../../docs/references/agscbs-sys.md)
> 后确认是**测试方法错误**（漏传系统盘开关）。已按正确方式重测并修正全部结论，见 §2。

---

## 1. 结论速览

| 项 | 结论 |
|---|---|
| 自定义沙箱模板创建 | ✅ 成功，`ToolType=custom` + `NetworkMode=SANDBOX` |
| CFS 存储模板挂载 | ✅ **可用**（`cedricbwang-cfs` → `/mnt/vt-cfs`） |
| COS 存储模板挂载 | ✅ **可用**（`cedricbwang-cos` → `/mnt/vt-cos`） |
| **AgentCBS 挂载** | ✅ **已打通**（数据卷 + 系统盘开关，见 §2） |
| 单机读写（256 MiB 顺序） | **CBS 写 128 / 冷读 79 MB/s**；CFS 写 58 / 读 87；COS 写 54 / 读 146 |
| 单机小文件（4K×2000） | **CBS 写 4.8s**；CFS 22.5s；COS **513s** |
| 跨实例持久化 | ✅ CBS/CFS/COS 均验证通过（sha256 一致） |
| 多机（2 实例并发） | CFS/COS 共享一致（CFS 写峰值 438 MB/s）；**CBS 为 RWO 独占，二次挂载被拒（符合预期）** |

> **三块存储全部挂载成功并完成性能测试。CBS 综合表现最好。**

---

## 2. AgentCBS 接入（已打通）

> 初版测试曾判定「CBS 不可用」——那是**误判**。真实原因是漏传了系统盘开关，
> 详见 §2.2。按 [agscbs-disk.md](../../docs/references/agscbs-disk.md) / [agscbs-sys.md](../../docs/references/agscbs-sys.md) 修正后 CBS 已完整跑通。

### 2.1 三块存储模板实际配置（`DescribeVolumeTemplateList`）

| VolumeTemplateId | 名称 | StorageType | AccessMode | 后端 |
|---|---|---|---|---|
| `volt-q4t7c0ei` | `cedricbwang-cbs` | **AgentCbs** | ReadWriteOnce | 20Gi |
| `volt-o8i4iftw` | `cedricbwang-cfs` | Cfs | ReadWriteMany | `cfs-47dff608c` + `/cedricbwang/${reuse_key}` |
| `volt-4fhc8td8` | `cedricbwang-cos` | Cos | ReadWriteMany | `cedricbwang-public-1258272081` + `test/${reuse_key}` |

### 2.2 踩坑：CBS 必须同时传「系统盘开关」

**错误做法**（初版）：只在工具级 `StorageMounts` 里引用 `VolumeTemplate{cedricbwang-cbs}`，
启动实例必然失败：

```
UnsupportedOperation.SandboxInstance
AgentCBS Volume requires an AgentCBS SystemDisk instance
```

**正确做法**（[agscbs-sys.md](../../docs/references/agscbs-sys.md) + [agscbs-disk.md](../../docs/references/agscbs-disk.md)）：

1. AgentCBS **数据盘**用独立的 `Volume` 资源管理，**不走** `VolumeTemplate` 的 `StorageMounts`；
   先 `CreateVolume` 创建 `StorageType=AgentCbs` 的数据卷，等 `Status=ACTIVE` 拿到 `VolumeId`；
2. 创建实例时**同时**传两样东西，缺一不可：
   - `StorageMounts[].Volume.VolumeId` + `MountPath`（数据盘挂载）
   - `Metadata: x-ags-agent-cbs-system-disk = "true"`（**AgentCBS 系统盘开关**）

```json
{
  "ToolId": "<custom ToolId>",
  "Timeout": "600s",
  "StorageMounts": [
    { "Name": "agent-data", "Volume": { "VolumeId": "vol-..." }, "MountPath": "/workspace/data" }
  ],
  "Metadata": [ { "Name": "x-ags-agent-cbs-system-disk", "Value": "true" } ]
}
```

E2B SDK 方式则在 `Sandbox.create(metadata={...})` 里同时给 `x-ags-agent-cbs-system-disk` 和
`x-storage`（JSON 字符串、**小驼峰** `volumeId`/`mountPath`）：

```python
Sandbox.create(template=tool_id, timeout=3600, metadata={
    "x-ags-agent-cbs-system-disk": "true",
    "x-storage": json.dumps([{
        "name": "agent-data",
        "volume": {"volumeId": VID},
        "mountPath": "/workspace/data",
    }]),
})
```

### 2.3 其余踩坑

| # | 坑 | 说明 |
|---|---|---|
| 1 | 值必须是字符串 `"true"` | 不能写 JSON 布尔 `true` |
| 2 | 系统盘开关返回后不可见 | 返回的 metadata 里**不保留**该键，不代表失败 |
| 3 | RWO 独占 | 卷被实例占用时二次挂载报 `409 ResourceInUse`；停止原实例并等卷释放（`MountedInstanceId` 变空）后才能换实例 |
| 4 | 一个实例最多一块 CBS 数据盘 | 不支持共享读写、只读挂载、SubPath、挂到根 `/` |
| 5 | 无需格式化 | 平台已格式化为 ext4，**切勿**在需保留数据的卷上 `mkfs` |
| 6 | 已有实例不能切换 | 不能通过更新 metadata 把普通系统盘换成 AgentCBS，必须新建实例 |
| 7 | 仅支持 custom | 内置 code-interpreter / browser 等类型不支持 |

### 2.4 挂载结果验证

```
TARGET          SOURCE   FSTYPE OPTIONS
/workspace/data /dev/vda ext4   rw,relatime

Filesystem  Size  Used Avail Use% Mounted on
/dev/vda     20G   24K   19G   1% /workspace/data
overlay2    974M   15M  893M   2% /
virtio_rw   500M  176M  325M  36% /mnt/vt-cfs
virtio_rw   500M  176M  325M  36% /mnt/vt-cos
```

**三块存储同时挂载成功。**

---

## 3. 自定义沙箱模板创建

### 请求要点

```json
{
  "ToolName": "agstest-vt-<ts>",
  "ToolType": "custom",
  "NetworkConfiguration": { "NetworkMode": "SANDBOX" },
  "DefaultTimeout": "1h",
  "RoleArn": "<ags-tcr-full 角色>",
  "StorageMounts": [
    { "Name": "vt-cfs", "MountPath": "/mnt/vt-cfs",
      "VolumeTemplate": { "VolumeTemplateName": "cedricbwang-cfs", "ReuseKey": "bench" } },
    { "Name": "vt-cos", "MountPath": "/mnt/vt-cos",
      "VolumeTemplate": { "VolumeTemplateName": "cedricbwang-cos", "ReuseKey": "bench" } }
  ],
  "CustomConfiguration": {
    "Image": "euson-tcr.tencentcloudcr.com/sandbox/sandbox:v1",
    "ImageRegistryType": "enterprise",
    "Command": ["sh"], "Args": ["-c", "/usr/bin/envd -port 49983"],
    "Ports": [{ "Name": "envd", "Port": 49983, "Protocol": "TCP" }],
    "Resources": { "CPU": "4000m", "Memory": "8192Mi" },
    "Probe": { "HttpGet": { "Path": "/health", "Port": 49983, "Scheme": "HTTP" }, "...": "..." }
  }
}
```

### 踩坑点

| # | 坑 | 说明 / 解法 |
|---|---|---|
| 1 | **存储模板引用用 Name，不用 ID** | `VolumeTemplate` 字段是 `VolumeTemplateName`（如 `cedricbwang-cfs`），**不是** `volt-*` ID。`volt-*` 只能通过 `DescribeVolumeTemplateList` 查询到 |
| 2 | **SDK 无 VolumeTemplate API** | 已安装 SDK（2025-09-20）没有 `DescribeVolumeTemplateList` / `VolumeTemplate` 字段，必须用 `call_json` 透传 |
| 3 | **SANDBOX 模式不能带 VpcConfig** | 否则报错；SANDBOX/PUBLIC 只传 `NetworkMode` |
| 4 | **CFS PathPattern 目录必须预先存在** | 模板为 `/cedricbwang/${reuse_key}`，若 `/cedricbwang/bench` 不存在则启动报 `FailedOperation.StorageMount ... path not found`。需先在 CFS 上建目录 |
| 5 | **建 CFS 目录不能从本机做** | 本机不在 CFS VPC（`30.1.3.5:2049` 不通）。解法：临时起一个 VPC 模式 + 旧版 `StorageSource.Cfs` 的沙箱，在沙箱内 `mkdir -p` |
| 6 | **一次请求挂载上限 10 项** | 工具级/实例级均限 10 条 StorageMounts |
| 7 | **实例级不支持 VolumeTemplate** | 只能在**工具级**用 `VolumeTemplate`；实例级只支持 `Volume` 或旧版 `StorageSource` |

---

## 4. 单机读写性能

测试方法：`dd` 顺序读写 256 MiB（`conv=fdatasync` + `sync`），`/dev/zero` 零数据。

| 存储 | 顺序写 | 顺序读（冷读） | 备注 |
|---|---|---|---|
| **CBS** (`/workspace/data`, ext4) | **128 MB/s**（2.10s） | **79.3 MB/s**（3.38s） | 块设备,最均衡 |
| CFS (`/mnt/vt-cfs`) | 58.1 MB/s（4.62s） | 86.9 MB/s（3.09s） | |
| COS (`/mnt/vt-cos`) | 53.6 MB/s（5.01s） | 146 MB/s（1.84s） | 读快写慢 |

> ⚠️ CBS 首次测得「读 13.1 GB/s」，是**页缓存**导致的假象（刚写完数据仍在内存）。
> 上表为 `echo 3 > /proc/sys/vm/drop_caches` 后的**冷读**真实值。

**观察**：
- **CBS 顺序写最快**（128 MB/s），约为 CFS/COS 的 2.2–2.4 倍——块设备绕过了网络文件系统协议栈；
- CBS 读写比约 1.6:1，是三者中最均衡的；
- COS 冷读 146 MB/s 虽最高，但写只有 54 MB/s，写放大明显；
- CFS 读写均在 50–90 MB/s，表现居中。

---

## 5. 小文件 / 中小文件性能

| 存储 | 4K × 2000 写 | 4K × 2000 读（冷） | 1MB × 100 写 | 1MB × 100 读（冷） |
|---|---|---|---|---|
| **CBS** | **4.78 s（≈419 ops/s）** | 5.70 s(≈351 ops/s) | **0.45 s（≈223 MB/s）** | 3.37 s（≈30 MB/s） |
| **CFS** | 22.5 s（≈89 ops/s） | 31.8 s（≈63 ops/s） | 1.29 s（≈77 MB/s） | 1.94 s（≈52 MB/s） |
| **COS** | **512.8 s（≈4 ops/s）** | 8.5 s | 22.3 s（≈4.5 MB/s） | 0.56 s（≈178 MB/s） |

**关键发现**：

1. **COS 小文件写入极差**——2000 个 4K 文件耗时 **513 秒**（每个约 256ms），
   比 CBS 慢 **107 倍**、比 CFS 慢 **23 倍**。原因：COS 经 FUSE 挂载后每次写入都是一次对象 PUT。
2. **CBS 小文件写最优**——4.78s，约 419 ops/s，是 CFS 的 4.7 倍；1MB 写 223 MB/s 也是最快。
3. **CBS 1MB 冷读偏慢**（30 MB/s，低于 CFS 的 52 和 COS 的 178）——与 §4 的 256MiB 冷读 79 MB/s 对比，
   说明 CBS 在**大量小文件逐文件读**时随机 IO 有额外开销；顺序大块读则正常。

**选型结论**：
- **小文件/元数据密集（代码、配置、checkpoint）→ CBS**（若可用且能接受 RWO 独占），其次 CFS
- **COS 只适合大文件**，小文件场景基本不可用

---

## 6. 多机（2 实例并发读写）

### 6.1 CFS / COS（ReadWriteMany）

两个实例挂载**同一** CFS/COS 模板、**同一 ReuseKey**（`bench`），并发各写 256 MiB。

| 实例 | 存储 | 顺序写 | 顺序读 |
|---|---|---|---|
| M1 | CFS | 39.9 MB/s（6.72s） | 162 MB/s（1.65s） |
| M2 | CFS | **438 MB/s**（0.61s） | 303 MB/s（0.89s） |
| M1 | COS | 30.5 MB/s（8.79s） | 157 MB/s（1.71s） |
| M2 | COS | **209 MB/s**（1.28s） | 170 MB/s（1.58s） |

### 6.2 CBS（ReadWriteOnce，独占）

CBS 数据卷为 **RWO 独占**，不支持多机共享。实测第二个实例挂载同一卷：

```
409: [ResourceInUse] ReadWriteOnce volume is reserved or mounted by another instance
```

**符合文档预期**。CBS 的多机场景只能「停止→换实例」，不能并发。

### 6.3 数据一致性验证 ✅

- **CFS/COS**：两个实例 `ls` 均能看到对方写入的文件（`M1.bin` / `M2.bin` 互相可见）；
  M1 写 `xcheck.txt` → M2 立即读到 `SHARED-CHECK` → 共享存储与跨实例可见性正常。
- **CBS 跨实例持久化**：实例 A 写 `agentcbs-check-demo.txt`（sha256 `ef59db1c...`）→ kill A →
  等卷释放 → 实例 B 挂同一卷读回，**sha256 完全一致，PERSIST_PASS**。

### 6.4 观察

- 同 ReuseKey 时两个实例**共享同一目录**，符合 ReadWriteMany 语义；
- **单实例间的性能离散度很大**（M1 39.9 vs M2 438 MB/s，相差 11 倍），
  说明结果受**沙箱所在宿主机/存储节点**差异影响显著，单次测量不宜作为绝对基准；
- 测到的最高值（CFS 438 MB/s、COS 209 MB/s）说明链路带宽上限远高于单机均值。

---

## 7. 使用建议

| 场景 | 推荐 |
|---|---|
| 小文件多、目录操作频繁（代码、配置、checkpoint） | **CBS**（最快，但 RWO 独占）；需多机共享则用 **CFS** |
| 大文件顺序读写（模型权重、数据集、归档） | **COS**（读快）或 CFS 均可 |
| 需要 RWO 独占块设备（数据库等） | **CBS**（记住必须带 `x-ags-agent-cbs-system-disk=true`） |
| 多实例共享同一份数据 | CFS/COS 均可（ReadWriteMany），用**相同 ReuseKey** |
| 需要实例间隔离 | 用**不同 ReuseKey**（派生不同数据卷） |

---

## 8. 待确认 / 后续

| 项 | 说明 |
|---|---|
| CBS 多机性能 | RWO 独占，无法并发测量；如需对比需改用可共享后端 |
| 多机性能离散度根因 | M1/M2 差 11 倍，需多次重复取中位数，并记录宿主机差异 |
| CBS 1MB 冷读偏低（30 MB/s） | 是否与逐文件读取模式有关，需用 fio 随机/顺序 IO 进一步区分 |
| COS 小文件优化 | 是否可通过挂载参数（如元数据缓存、并发 PUT）改善 4K 写性能 |
| 旧版 StorageSource 与 VolumeTemplate 差异 | 两者挂载同一后端时的性能/语义差异未对比 |
