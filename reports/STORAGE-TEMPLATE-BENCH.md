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

---

## 1. 结论速览

| 项 | 结论 |
|---|---|
| 自定义沙箱模板创建 | ✅ 成功，`ToolType=custom` + `NetworkMode=SANDBOX` |
| CFS 存储模板挂载 | ✅ **可用**（`cedricbwang-cfs` → `/mnt/vt-cfs`） |
| COS 存储模板挂载 | ✅ **可用**（`cedricbwang-cos` → `/mnt/vt-cos`） |
| **AgentCBS 存储模板挂载** | ❌ **不可用**（见 §2，产品限制） |
| 单机读写 | CFS 写 58 MB/s / 读 87 MB/s；COS 写 54 MB/s / 读 146 MB/s |
| 多机（2 实例并发） | 共享存储一致；CFS 写峰值 438 MB/s，COS 写 209 MB/s |
| 小文件性能 | **CFS 可接受，COS 极差**（4K×2000 写 513s，见 §5） |

> 三块存储中，**两块（CFS/COS）成功挂载并完成性能测试；CBS 被产品能力阻塞**。

---

## 2. 关键阻塞：AgentCBS 暂不支持

### 现象

创建挂载 CBS 模板的工具可以成功（工具状态 ACTIVE、回查配置一致），但**启动实例必然失败**：

```
UnsupportedOperation.SandboxInstance
AgentCBS Volume requires an AgentCBS SystemDisk instance
```

### 三块存储模板实际配置（`DescribeVolumeTemplateList`）

| VolumeTemplateId | 名称 | StorageType | AccessMode | 后端 |
|---|---|---|---|---|
| `volt-q4t7c0ei` | `cedricbwang-cbs` | **AgentCbs** | ReadWriteOnce | 20Gi |
| `volt-o8i4iftw` | `cedricbwang-cfs` | Cfs | ReadWriteMany | `cfs-47dff608c` + `/cedricbwang/${reuse_key}` |
| `volt-4fhc8td8` | `cedricbwang-cos` | Cos | ReadWriteMany | `cedricbwang-public-1258272081` + `test/${reuse_key}` |

### 根因（两层）

1. **官方能力限制**：Agent Runtime 存储管理文档明确写
   「多后端支持：当前支持对象存储（COS）和文件存储（CFS）两类后端，**AgentCBS 即将支持**」；
   数据卷文档的使用限制也写「当前仅支持 COS 与 CFS；其他存储类型暂不支持」。
2. **缺少系统盘配置入口**：报错要求实例具备 **AgentCBS 系统盘**，但当前 SDK/API 版本的
   `CustomConfiguration` 仅有 `Image/ImageRegistryType/Command/Args/Env/Ports/Resources/Probe/DNSConfig`，
   **没有设置系统盘类型的字段**。逐一探测 `SystemDisk` / `DiskType` / `SystemDiskType` /
   `Resources.SystemDisk` / `ComputerConfiguration.SystemDisk` 均返回 `UnknownParameter`。

**结论**：`volt-q4t7c0ei` 属于灰度/预览阶段的资源，当前测试账号的 API 链路无法真正拉起。
需等产品正式支持 AgentCBS 系统盘后复测。

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

| 存储 | 顺序写 | 顺序读 |
|---|---|---|
| CFS (`/mnt/vt-cfs`) | 58.1 MB/s（4.62s） | 86.9 MB/s（3.09s） |
| COS (`/mnt/vt-cos`) | 53.6 MB/s（5.01s） | 146 MB/s（1.84s） |

**观察**：
- 两者顺序吞吐都在 **50–150 MB/s** 量级，差距不大；
- COS 读明显快于写（146 vs 54 MB/s），符合对象存储「写放大、读缓存」特征；
- CFS 读写较均衡。

---

## 5. 小文件 / 中小文件性能

| 存储 | 4K × 2000 写 | 4K × 2000 读 | 1MB × 100 写 | 1MB × 100 读 |
|---|---|---|---|---|
| **CFS** | 22.5 s（≈178 ops/s） | 31.8 s（≈126 ops/s） | 1.29 s（≈77 MB/s） | 1.94 s（≈52 MB/s） |
| **COS** | **512.8 s（≈4 ops/s）** | 8.5 s | 22.3 s（≈4.5 MB/s） | 0.56 s（≈178 MB/s） |

**关键发现：COS 的小文件写入性能极差**——2000 个 4K 文件写入耗时 **513 秒**（每个约 256ms），
而 CFS 仅 22.5s，相差 **23 倍**。原因是 COS 经 FUSE 挂载后每个写入都对应一次对象 PUT 请求。
- **COS 只适合大文件**（顺序读写 50–150 MB/s 尚可）；
- **小文件、高频元数据操作必须用 CFS**。

---

## 6. 多机（2 实例并发读写）

两个实例挂载**同一** CFS/COS 模板、**同一 ReuseKey**（`bench`），并发各写 256 MiB。

| 实例 | 存储 | 顺序写 | 顺序读 |
|---|---|---|---|
| M1 | CFS | 39.9 MB/s（6.72s） | 162 MB/s（1.65s） |
| M2 | CFS | **438 MB/s**（0.61s） | 303 MB/s（0.89s） |
| M1 | COS | 30.5 MB/s（8.79s） | 157 MB/s（1.71s） |
| M2 | COS | **209 MB/s**（1.28s） | 170 MB/s（1.58s） |

### 数据一致性验证 ✅

- 两个实例 `ls` 均能看到对方写入的文件（`M1.bin` / `M2.bin` 互相可见）；
- M1 写 `xcheck.txt` → M2 立即读到 `SHARED-CHECK` → **共享存储与跨实例可见性正常**。

### 观察

- 同 ReuseKey 时两个实例**共享同一目录**，符合 ReadWriteMany 语义；
- **单实例间的性能离散度很大**（M1 39.9 vs M2 438 MB/s，相差 11 倍），
  说明结果受**沙箱所在宿主机/存储节点**差异影响显著，单次测量不宜作为绝对基准；
- 测到的最高值（CFS 438 MB/s、COS 209 MB/s）说明链路带宽上限远高于单机均值。

---

## 7. 使用建议

| 场景 | 推荐 |
|---|---|
| 小文件多、目录操作频繁（代码、配置、checkpoint） | **CFS** |
| 大文件顺序读写（模型权重、数据集、归档） | **COS**（读快）或 CFS 均可 |
| 需要 RWO 独占块设备（数据库等） | 暂不可用，等 AgentCBS 支持 |
| 多实例共享同一份数据 | CFS/COS 均可（ReadWriteMany），用**相同 ReuseKey** |
| 需要实例间隔离 | 用**不同 ReuseKey**（派生不同数据卷） |

---

## 8. 待确认 / 后续

| 项 | 说明 |
|---|---|
| AgentCBS 正式可用时间 | 需产品侧确认；当前报错要求 AgentCBS 系统盘，但 API 无对应字段 |
| 多机性能离散度根因 | M1/M2 差 11 倍，需多次重复取中位数，并记录宿主机差异 |
| ReadWriteOnce 数据卷多实例行为 | 文档称「一个沙箱最多引用一个 RWO 数据卷」，CBS 可用后需验证二次挂载是否被拒 |
| COS 小文件优化 | 是否可通过挂载参数（如元数据缓存、并发 PUT）改善 4K 写性能 |
| 旧版 StorageSource 与 VolumeTemplate 差异 | 两者挂载同一后端时的性能/语义差异未对比 |
