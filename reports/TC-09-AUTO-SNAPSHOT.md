# TC-09 auto-snapshot 启动速度对照测试

| 项 | 值 |
|---|---|
| 测试例编号 | TC-09 |
| 测试目标 | 验证「工具名以 `auto-snapshot` 结尾」是否触发自动快照并加速实例拉起 |
| 地域 | `ap-beijing` |
| 网络模式 | `SANDBOX` |
| 镜像 | `euson-tcr.tencentcloudcr.com/cedricbwang/test:v1` |
| 规格 | 2C / 4Gi |
| 测试日期 | 2026-11-06 |
| 脚本 | `scripts/tc06_auto_snapshot.py` |
| 原始数据 | `reports/artifacts/tc09-auto-snapshot.json` |
| 结论 | ⚠️ **无显著差异** —— 后缀未产生可观测的快照加速 |

---

## 1. 测试设计

### 1.1 对照组构建

创建两个**配置完全一致**的 custom 工具，唯一差异是名称：

| 分组 | 工具名 | 说明 |
|---|---|---|
| 对照组（plain） | `agstest-plain-<ts>` | 普通命名 |
| 实验组（snap） | `agstest-snapshot-auto-snapshot-<ts>` | 名称**结尾包含** `auto-snapshot` |

两者相同项：镜像、`ImageRegistryType`、启动命令 `sh -c "/usr/bin/envd -port 49983"`、
端口、`Resources`（2C/4Gi）、健康检查、网络模式、`RoleArn`、`DefaultTimeout`。

> 控制变量原则：除工具名后缀外不引入任何其他差异，确保观测到的任何性能变化只可能来自后缀。

### 1.2 测量维度

| 编号 | 维度 | 方法 | 轮次 |
|---|---|---|---|
| TC-09-A | Cloud API 启动耗时 | `StartSandboxInstance` → 轮询至 `RUNNING` | 3 |
| TC-09-B | E2B 端到端创建 | `Sandbox.create()` 返回耗时 + 首条命令往返 | 5 |
| TC-09-C | 并发拉起 | 8 路并发 `Sandbox.create()` 的总墙钟与均值 | 1 批 |
| TC-09-D | 配置一致性 | 回查工具配置，比对是否有快照相关字段 | 1 |

每轮之间：显式 `stop_instance` / `kill` 并等待回收，避免实例复用干扰下一轮。

---

## 2. 测试结果

### TC-09-A Cloud API 启动耗时（秒）

| 轮次 | plain | auto-snapshot |
|---|---|---|
| r1 | 4.525 | 4.612 |
| r2 | 4.466 | 4.353 |
| r3 | 4.471 | 4.263 |
| **均值** | **4.487** | **4.409** |
| 中位数 | 4.471 | 4.353 |

差异 **-1.74%**（snap 略快），在噪声范围内。

> 补充：`StartSandboxInstance` 接口本身固定耗时约 **4.2–4.5s**，这部分是控制面同步开销，
> 与实例是否快照启动无关，会稀释启动差异。

### TC-09-B E2B 端到端创建（秒）

| 轮次 | plain create | plain first_cmd | snap create | snap first_cmd |
|---|---|---|---|---|
| r1 | 4.544 | 4.716 | 4.273 | 4.442 |
| r2 | 4.417 | 4.582 | 3.978 | 4.165 |
| r3 | 4.365 | 4.475 | 4.745 | 4.929 |
| r4 | 4.233 | 4.290 | 4.021 | 4.091 |
| r5 | 4.388 | 4.552 | 4.300 | 4.512 |
| **均值** | **4.389** | **4.523** | **4.263** | **4.428** |
| 中位数 | 4.388 | — | 4.273 | — |
| 最小 / 最大 | 4.233 / 4.544 | — | **3.978** / **4.745** | — |

差异 **-2.87%**（snap 略快）。注意 snap 组极差更大（3.978–4.745，跨度 0.77s），
而 plain 组为 4.233–4.544（跨度 0.31s）——说明 snap 组的波动来自环境抖动，而非稳定加速。

### TC-09-C 并发 8 路拉起（秒）

| 指标 | plain | auto-snapshot |
|---|---|---|
| 总墙钟 | **5.09** | 5.27 |
| 成功 / 失败 | 8 / 0 | 8 / 0 |
| 单实例均值 | 4.565 | 4.555 |
| 单实例最大 | **4.651** | 4.844 |

两者总墙钟都在 5.1–5.3s，**8 个实例几乎同时就绪**，说明平台并发拉起本身已很快，
快照若生效，理论上应进一步压低冷启动路径耗时，但实测未见。

### TC-09-D 配置一致性

回查两个工具的完整配置，字段列表完全相同：

```
AccessPolicyIds, AutoPause, AutoResume, CreateTime, CustomConfiguration,
DefaultTimeoutSeconds, Description, KeepaliveConfiguration, NetworkConfiguration,
Persistent, RoleArn, Status, StatusReason, Tags, ToolId, ToolName, ToolType, UpdateTime
```

| 字段 | plain | auto-snapshot |
|---|---|---|
| `AutoPause` / `AutoResume` | False / False | False / False |
| `Persistent` | False | False |
| `KeepaliveConfiguration` | REQUEST / 10m | REQUEST / 10m |
| `Tags` | `[]` | `[]` |
| 快照相关字段 | **无** | **无** |

**控制面没有为 `auto-snapshot` 后缀生成任何特殊配置**，两个工具在服务端完全等价。

---

## 3. 结论

| 检查点 | 结论 |
|---|---|
| TC-09-A API 启动耗时差异 | ⚠️ -1.74%，噪声范围 |
| TC-09-B E2B 创建耗时差异 | ⚠️ -2.87%，噪声范围 |
| TC-09-C 并发拉起差异 | ❌ 无差异（snap 反而慢 0.18s） |
| TC-09-D 配置是否特殊化 | ❌ 完全一致，无快照字段 |

**综合判定：在当前 AGS 环境（`ap-beijing`，API `2025-09-20`）下，
工具名结尾包含 `auto-snapshot` 不会触发自动快照，也不带来可测量的启动加速。**

三个维度差异均在 ±3% 内，低于测量噪声，且配置回查证实服务端未做任何区分处理。

### 3.1 可能的解释

1. **该约定不存在**：`auto-snapshot` 不是公开的命名约定，公开文档中也无此约定。
2. **需要额外开关**：快照加速可能需要控制台/API 侧显式配置（如模板快照、
   镜像预热），仅靠命名不生效。
3. **灰度未开放**：该能力可能处于灰度阶段，当前账号未开通。

### 3.2 关于「毫秒级启动」的说明

产品宣传的 60ms / 毫秒级冷启动，与本次实测的 **4.2–4.8s** 存在数量级差距。
本次测量包含：`StartSandboxInstance` 控制面同步调用（约 4.2–4.5s）+ 实例实际拉起。
若要贴近产品宣称的指标，应改为**测量纯数据面路径**（预热后再建实例），
或使用批量/常驻池模式，这属于另一组测试设计。

---

## 4. 复现方式

```bash
# 完整对照测试（约 6 分钟，自动建/删工具与实例）
python3 scripts/tc06_auto_snapshot.py

# 调整轮次
python3 scripts/tc06_auto_snapshot.py --rounds 10 --api-rounds 5 --concurrency 16

# 保留资源排障
python3 scripts/tc06_auto_snapshot.py --keep
```

脚本结束输出汇总表并写入 `reports/artifacts/tc09-auto-snapshot.json`；
内置 `CleanupRegistry` 自动回收工具与实例。

---

## 5. 局限与后续

| 项 | 说明 |
|---|---|
| 网络模式 | 本组用 `SANDBOX`；`PUBLIC` / `VPC` 下是否一致未验证 |
| 镜像选择 | 使用自建小镜像；大镜像（依赖多）冷启动更慢，快照收益理论上更明显，建议补测 |
| 首实例 vs 稳态 | 未区分「该镜像首次拉取」与「已有缓存」两种情况 |
| 真实快照路径 | 若产品确提供模板快照，应按其文档单独设计用例（制作快照 → 从快照建实例 → 计时） |
| 样本量 | 每组 5 轮；如需统计显著性检验，建议 ≥30 轮并剔除异常值 |
