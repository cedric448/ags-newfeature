# TC-11 镜像预热（PreCacheImage）接口测试

| 项 | 值 |
|---|---|
| 测试例编号 | TC-11 |
| 测试目标 | 验证镜像预热接口的创建、查询、列表与幂等性 |
| 地域 | `ap-beijing` |
| 测试日期 | 2026-11-07 |
| 脚本 | `scripts/tc11_precache.py` |
| 原始数据 | `reports/artifacts/tc11-precache.json` |
| 结论 | ✅ **PASS 14/14** |

---

## 1. 接口清单

| 接口 | 用途 | 关键参数 |
|---|---|---|
| `CreatePreCacheImageTask` | 提交预热任务 | `Image`、`ImageRegistryType` |
| `DescribePreCacheImageTask` | 查询单镜像预热状态 | `Image`+`ImageRegistryType`，或 `PreCacheImageId` |
| `DescribePreCacheImageList` | 列出全部预热记录 | `NextToken` 分页 |

> **注意**：SDK（`tencentcloud.ags.v20250920`）的 `DescribePreCacheImageTaskRequest` 模型
> **不含 `PreCacheImageId` 字段**，但 API 实际支持。需通过 `ags.call()` 直接传参绕过 SDK 模型校验。

---

## 2. 预热记录现状

当前账号共 **11 条**预热记录，全部 `Success`：

| PreCacheImageId | 来源 | 大小 | 镜像 |
|---|---|---|---|
| pcimg-q6zid549 | AUTO | 5.70 GiB | `cedricbwang/test:v1` |
| pcimg-ap3jzbhp | AUTO | 4.39 GiB | `sandbox/sandbox:v1` |
| pcimg-0hrtd4nf | AUTO | 3.06 GiB | `csig_yuanbao_openclaw/openclaw` |
| pcimg-5ffr467j | AUTO | 1.68 GiB | `picoclaw/picoclaw:1.2.20` |
| pcimg-5fdmv2m9 | **EXPLICIT** | 0.32 GiB | `ags_test/gpu-sandbox-test:v1.0` |
| pcimg-eb2b27j7 | AUTO | 0.39 GiB | `tcr_sandbox_rl:evocode` |
| pcimg-qqg2vekv | AUTO | 0.32 GiB | `tcr_sandbox_rl:youtu-agent` |
| pcimg-4g4bt62x / 9ljsddfv / at9yzn4d | AUTO | 0.13 GiB ×3 | `tcr-temple:net-test` |
| pcimg-h758rukl | AUTO | 0.01 GiB | `swebench/dummy:latest` |

**关键观察：10 条为 `AUTO`（自动预热），仅 1 条为 `EXPLICIT`（调用接口显式提交）。**

这说明平台存在**自动预热机制**：工具启动实例时，镜像会被自动加入预热缓存，
用户通常**不需要手动调用预热接口**。

### 2.1 全部工具镜像均已被预热覆盖

| Tool 数 | 镜像已预热 | 覆盖率 |
|---|---|---|
| 12（有镜像的 custom 工具） | 12 | **100%** |

---

## 3. 接口返回字段（比 SDK 模型丰富）

`DescribePreCacheImageTask` 实际返回：

| 字段 | 说明 | SDK 模型有？ |
|---|---|---|
| `PreCacheImageId` | 预热记录 ID，`pcimg-` 前缀 | ❌ **无** |
| `Image` / `ImageDigest` | 镜像地址与摘要 | ✅ |
| `ImageRegistryType` | `personal` / `enterprise` / `system` | ✅ |
| `Status` | `Success` 等 | ✅ |
| `Message` | 如 `Image precache completed successfully` | ✅ |
| `CachedImageSizeBytes` | 缓存体积（字节） | ❌ **无** |
| `SourceType` | `AUTO` / `EXPLICIT` | ❌ **无** |
| `IdleTTL` | 空闲过期策略，如 `inherit` | ❌ **无** |
| `CreateTime` / `ReadyTime` | 创建/就绪时间 | ❌ **无** |
| `LastUsedTime` | 最近使用时间 | ❌ **无** |
| `Scopes` | 创建接口返回，如 `["external"]` | ❌ **无** |

> **SDK 模型严重滞后于 API 实际返回值**，缺少 8 个字段。建议用户使用原始 call 或自行解析。

---

## 4. 检查点明细

| # | 检查项 | 结果 | 实测 |
|---|---|---|---|
| 1 | 列表接口可用 | ✅ | 11 条记录 |
| 2 | 记录含 `PreCacheImageId` | ✅ | 全部具备 |
| 3 | 记录含 `ImageDigest` | ✅ | 全部具备 |
| 4 | 按 Image 查询成功 | ✅ | `Status=Success` |
| 5 | 状态为 Success | ✅ | — |
| 6 | 按 `PreCacheImageId` 查询成功 | ✅ | 绕过 SDK 模型 |
| 7 | 重复提交成功 | ✅ | 270ms |
| 8 | **返回同一 `PreCacheImageId`** | ✅ | `pcimg-q6zid549` |
| 9 | 返回 `Scopes` 字段 | ✅ | `["external"]` |
| 10 | **`CreateTime` 未变化（幂等）** | ✅ | `2026-10-10T18:00:30` |
| 11 | 不存在的镜像被拒 | ✅ | `ResourceNotFound.Image` |
| 12 | 缺 `ImageRegistryType` 被拒 | ✅ | `MissingParameter` |
| 13 | 查询缺 registry type 被拒 | ✅ | `InvalidParameter` |
| 14 | 列表不支持参数被拒 | ✅ | `UnknownParameter` |

---

## 5. 关键发现

### 5.1 创建接口是幂等的

对已预热的镜像重复调用 `CreatePreCacheImageTask`：

- 返回**同一个** `PreCacheImageId`
- `CreateTime` **保持原值不变**（未被刷新）
- **不会**触发重新预热

这一行为对运维友好：可以放心在启动脚本里无脑调用预热接口，不会造成重复拉取。

### 5.2 存在自动预热（AUTO）机制

11 条记录中 10 条 `SourceType=AUTO`，说明平台在工具/实例启动时自动预热镜像。
用户观察到「从未手动预热，但查询显示 Success」属于正常现象，**不是 bug**。

### 5.3 SDK 模型与 API 不一致（质量问题）

| 问题 | 影响 |
|---|---|
| `DescribePreCacheImageTaskRequest` 缺 `PreCacheImageId` | 无法通过强类型模型按 ID 查询 |
| `DescribePreCacheImageTaskResponse` 缺 8 个字段 | 无法获取 `SourceType`、`CachedImageSizeBytes` 等关键信息 |
| `DescribePreCacheImageList` 无对应 SDK 模型 | 无法使用强类型调用 |

### 5.4 分页使用 `NextToken`

列表接口**不支持** `Offset` / `PageSize` / `Limit`，传入会报 `UnknownParameter`。
分页必须用 `NextToken`（当前 11 条记录一页返回完毕）。

---

## 6. 预热效果实测

对已预热镜像（`sandbox/sandbox:v1`，4.39 GiB）连续启动 5 次：

| 轮次 | 启动耗时 |
|---|---|
| r1 | 5.30 s |
| r2 | 4.81 s |
| r3 | 4.87 s |
| r4 | 4.57 s |
| r5 | 4.43 s |
| **中位数** | **4.81 s** |

> 注：该耗时包含 `StartSandboxInstance` 控制面同步调用（约 4s），
> 预热对端到端启动的加速效果被控制面开销稀释。
> 若要测量纯镜像拉取加速，需对照**从未预热**的镜像，但当前账号所有工具镜像均已预热，
> 无法获得有效对照样本。

---

## 7. 结论

| 项 | 结论 |
|---|---|
| 预热创建/查询/列表接口 | ✅ 均可用 |
| 幂等性 | ✅ 重复提交不重复预热 |
| 负例校验 | ✅ 4/4 按预期拒绝 |
| 自动预热机制 | ✅ 存在，覆盖全部工具镜像 |
| SDK 模型完整性 | ⚠️ 缺少 `PreCacheImageId` 及 8 个返回字段 |

**镜像预热能力工作正常。用户无需手动预热，平台会在实例启动时自动完成；
如需显式预热可用 `CreatePreCacheImageTask`，且可安全重复调用。**

---

## 8. 复现方式

```bash
python3 scripts/tc11_precache.py                # 全量测试
python3 scripts/tc11_precache.py --list         # 只列记录
python3 scripts/tc11_precache.py --verify IMG   # 校验指定镜像
```

---

## 9. 局限

| 项 | 说明 |
|---|---|
| 未观察到 `Pending`/`Running` 中间态 | 所有记录均为 `Success`，镜像已全部预热；新镜像预热（如 `test:nginx`）因镜像不存在被拒 |
| 未测失败场景 | 需要构造拉取失败的镜像（如私有仓库无权限） |
| 未测 `IdleTTL` 过期淘汰 | 观察到字段存在但未验证淘汰行为 |
| 预热加速效果 | 缺未预热对照组，无法量化 |
