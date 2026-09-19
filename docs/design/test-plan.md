# 腾讯云 AGS 新功能测试方案（草案 v1）

> 目标：设计测试例 → 执行测试与验证 → 按每个测试例输出独立测试文档。
> Region：`ap-beijing`；AGS 域名：`ap-beijing.tencentags.com`
> 沙箱工具网络模式：`VPC`（`vpc-ovochv3a` / `subnet-pac3o08j` / ap-beijing-8）

---

## 0. 环境摸底结果（已验证）

> **2026-09-19 更新：TC-01 基线已打通并 PASS。** 详见 `testcases/TC-01-*.md`。

### 0.1 基线打通过程（关键结论）

原始阻塞 `FailedOperation.Timeout` 的根因**不是地域故障**，而是**工具配置不正确**。逐一踩坑如下：

| # | 报错 | 根因 | 解法 |
|---|---|---|---|
| 1 | `MissingParameter.RoleArn` | `ToolType=custom` + `ImageRegistryType` 为 `enterprise/personal` 时强制要求 `RoleArn` | 复用已有角色 `qcs::cam::uin/100008634787:roleName/ags-tcr-full` |
| 2 | `MissingParameter.VPCParameters` | VPC 模式**强制**要求 `SecurityGroupIds`（不只是 `SubnetIds`） | 新建安全组 `sg-p3sxc9y3`（`agstest-sg`，放通全部出入站），归属 `vpc-ovochv3a` |
| 3 | `ResourceNotFound.Image: image not found` | TCR 镜像地址必须用**实例域名**（`euson-tcr.tencentcloudcr.com`），不是实例 ID（`tcr-mvlaq1sq.tencentcloudcr.com`） | 改用 `euson-tcr.tencentcloudcr.com/sandbox/sandbox:v1` |
| 4 | `FailedOperation.ContainerStart` | 启动命令指向 `/mnt/envd-runtime/envd`，但该路径依赖额外的 image volume 挂载；镜像内已内置 `/usr/bin/envd` | 命令改为 `/usr/bin/envd -port 49983` |
| 5 | `InvalidParameter: InstanceIds.0 类型错误` | `StartSandboxInstance` 返回结构是 `{"Instance":{"InstanceId":...}}`，**不是**顶层 `InstanceId` | 解析 `resp["Instance"]["InstanceId"]` |

**可用的最小工具配置**（已验证可启动 RUNNING）：

```json
{
  "ToolName": "agstest-tc01-<ts>",
  "ToolType": "custom",
  "RoleArn": "qcs::cam::uin/100008634787:roleName/ags-tcr-full",
  "NetworkConfiguration": {
    "NetworkMode": "VPC",
    "VpcConfig": {"SubnetIds": ["subnet-pac3o08j"], "SecurityGroupIds": ["sg-p3sxc9y3"]}
  },
  "DefaultTimeout": "30m",
  "CustomConfiguration": {
    "Image": "euson-tcr.tencentcloudcr.com/sandbox/sandbox:v1",
    "ImageRegistryType": "enterprise",
    "Command": ["sh"],
    "Args": ["-c", "/usr/bin/envd -port 49983"],
    "Ports": [{"Name": "envd", "Port": 49983, "Protocol": "TCP"}],
    "Resources": {"CPU": "2000m", "Memory": "4096Mi"},
    "Probe": {
      "HttpGet": {"Path": "/health", "Port": 49983, "Scheme": "HTTP"},
      "ReadyTimeoutMs": 30000, "ProbeTimeoutMs": 2000, "ProbePeriodMs": 3000,
      "SuccessThreshold": 1, "FailureThreshold": 100
    }
  }
}
```

**观测到的行为**：
- envd 的 `/health` 返回 **HTTP 204**（不是 200），探针判定为成功。
- `vpc-ovochv3a` / `subnet-pac3o08j` **有公网出口**（`curl https://www.tencentcloud.com` 返回 200），即该子网已挂 NAT。

### 0.2 环境事实

| 项 | 结果 |
|---|---|
| 腾讯云 AK/SK | 可用（UIN `100008634787`） |
| SDK 版本 | `tencentcloud-sdk-python 3.1.63`，AGS 模块版本 **`v20250920`**（不是 `p.md` 里写的 v20250519） |
| E2B SDK | 已装 `e2b 2.21.0` + `e2b-code-interpreter 2.6.2`（文档建议组合是 2.23.1 + 2.2.1，**版本不一致**） |
| E2B_API_KEY | `ark_...` 格式，`E2B_DOMAIN=ap-beijing.tencentags.com` |
| 已有工具 | 13 个（3 个 code-interpreter、10 个 custom，含 VPC 模式） |
| VPC `vpc-ovochv3a` | 存在；默认子网 `subnet-pac3o08j`（172.21.128.0/20, ap-beijing-8）；已挂 NAT |
| 测试安全组 | **`sg-p3sxc9y3`（新建，`agstest-sg`）**，放通全部入站/出站 |
| CAM 角色 | `ags-tcr-full`（TCR/CCR 拉镜像，已被 5 个工具使用）、`lily-agent`、`TCR_QCSRole` |
| TCR | 实例 `tcr-mvlaq1sq`（域名 `euson-tcr.tencentcloudcr.com`）；镜像 `sandbox/sandbox:v1`（1.79GB，entrypoint `/init`，内置 `/usr/bin/envd`，Python 3.12.13） |
| CFS | 4 个普通 NFS 实例（`cfs-qr3xtqol` / `cfs-093u0f81` / `cfs-2zzozjy7` / `cfs-cunkkj23`），**均非 AgentCFS** |
| 跨境代理 | `startvpn` / `stopvpn` 函数可用（`127.0.0.1:1087`），开启后 GitHub 与 TCR 公网可访问 |

### 已探明的 API 能力面（v20250920）

- 沙箱工具：`CreateSandboxTool` / `DescribeSandboxToolList` / `UpdateSandboxTool` / `DeleteSandboxTool`
- 沙箱实例：`StartSandboxInstance` / `StopSandboxInstance` / `PauseSandboxInstance` / `ResumeSandboxInstance` / `UpdateSandboxInstance` / `DescribeSandboxInstanceList` / `AcquireSandboxInstanceToken`
- 弹性部署（Agent Engine）：`CreateDeployment` / `DescribeDeployment(List)` / `ModifyDeployment` / `DeleteDeployment` / `AcquireDeploymentToken`
- 其他：`CreateAPIKey` / `DeleteAPIKey` / `DescribeAPIKeyList` / `CreatePreCacheImageTask` / `DescribePreCacheImageTask`
- 存储：`StorageSource` 支持 `Cos` / `Cfs` / `Image` / **`AgentBucket`**（SDK 未发布 typed model，需 `call_json`）
- 桌面沙箱：`ComputerConfiguration.WAAConfiguration.ImageId`、`ComputerConfiguration.OSWorldConfiguration.Version`（`osworld1`/`osworld2`）

### 关键发现：文档与 p.md 的偏差

1. **"模板快照 / 沙箱快照"在 AGS 公开文档里不存在**。
   公开 API 没有 Snapshot 接口/数据结构，产品动态里只有一句"`SystemDiskSize` 字段，可在创建或快照相关流程中指定系统盘大小"。
   → 需要确认指的是：① 未公开的灰度 API；② 控制台的"镜像/系统盘快照"；③ 实为 `AcquireSandboxInstanceToken` / 持久化沙箱之类的别的功能。
2. **`p.md` 测试例编号重复**（3、4 各出现两次），共 7 项功能。
3. **"agent engine"** 在公开文档中对应 **弹性部署（Deployment, beta）**，仅上海、香港地域可用 —— **北京地域可能不支持**，需要调整测试地域或降级为文档验证。

---

## 1. 测试例清单与设计

**执行状态（2026-09-19）**

| 测试例 | 状态 | 报告 |
|---|---|---|
| TC-01 沙箱基线（TCR 镜像 + 启动打通） | ✅ PASS 10/10 | `reports/TC-01-VPC.md` |
| TC-02 AgentBucket 持久化存储 | ✅ PASS 17/17 | `reports/TC-02.md` |
| TC-03 Agent Engine 弹性部署 | ✅ PASS 17/17 | `reports/TC-03.md` |
| TC-04 AgentCFS 共享存储 | ⚠️ PASS 13/14（1 缺陷） | `reports/TC-04.md` |
| TC-05/06 模板快照 / 沙箱快照 | ⏭ SKIP（按决策暂缓） | — |
| TC-07/08 WAA / OSWorld | ⏭ SKIP（按决策暂缓） | — |

**累计：4 个测试例，59 个检查点，58 通过 / 1 失败（真实缺陷 BUG-01）。**

> 完整结论与关键发现见 **`reports/SUMMARY.md`**。

编号重排如下（**A/B/C 三档**：A=可立即执行，B=需额外资源/确认，C=需先澄清功能范围）。

### TC-01 沙箱基线（TCR 镜像 + 启动打通）—— 档位 A ✅ 已完成
> 原 p.md 未列此项，但在执行中成为所有后续测试的前置基线。

### TC-02 AgentBucket 使用 —— 档位 B ✅ 已完成
- **依据**：`docs/requirements/agentbucket.md` + 官方文档 137731
- **已完成 8 个用例**：见 `reports/TC-02.md`
- **使用资源**：LibraryId `smh3qv6cmcoscm4i`（`cedricbwang-agentbucket`）、spaceID `space3ly9r9ni7fhju`
  （通过 SMH 业务面 `GET /api/v1/space/{libraryId}/list` 自动发现）

### TC-03 Agent Engine（弹性部署 Deployment）—— 档位 B ✅ 已完成
- **已完成 9 个用例**：见 `reports/TC-03.md`
- **地域约束（实测）**：仅 `ap-shanghai` / `ap-hongkong` 支持；
  `ap-beijing` / `ap-guangzhou` / `ap-singapore` 返回 `UnsupportedRegion`
- **工具约束**：必须 `Persistent=true`，且仅 custom/mobile/android-world/osworld/waa 支持

### TC-04 AgentCFS 使用 —— 档位 B ✅ 已完成
- **依据**：`https://cloud.tencent.com/document/product/582/137338` + AGS 存储挂载文档 132215
- **已完成 7 个用例**：见 `reports/TC-04.md`
- **重要发现**：文档要求「架构类型 = Agent 文件系统」，但**实测普通 NFS 型 CFS
  （`cfs-cunkkj23`）也能被 AGS 正常接受并挂载读写**，无需额外创建 AgentCFS。
- **发现缺陷 BUG-01**：CFS 的实例级 `MountOptions.ReadOnly=true` 被接受但**未生效**
  （挂载仍为 `rw`，写入成功）；对照 AgentBucket 同类能力正常。

### TC-05 模板快照（Template Snapshot）—— 档位 C ⏭ 暂缓
### TC-06 沙箱快照（Sandbox Snapshot）—— 档位 C ⏭ 暂缓
> 公开 API / SDK / 产品动态均无 Snapshot 接口与数据结构，待明确功能形态。

### TC-07 WAA 沙箱 —— 档位 B（重） ⏭ 暂缓
> 上海地域已存在 `waa` 类型工具（`waa-2r4kdj2v8ae`），说明平台侧已支持。
> 执行需：WAA 兼容模板 + Windows 镜像 + OpenAI 兼容模型 + Python 3.10 + uv。

### TC-08 OSWorld 沙箱 —— 档位 B（中） ⏭ 暂缓
> 支持 `ComputerConfiguration.OSWorldConfiguration.Version`（`osworld1`/`osworld2`）。
> 执行需：OSWorld 兼容模板（含 socat/sudo）+ Python 3.12 + uv。

---

## 2. 横切测试项（每个测试例共用）

| 项 | 说明 |
|---|---|
| 网络模式 | 统一使用 `VPC` + `vpc-ovochv3a` / `subnet-pac3o08j`；校验 `NetworkConfiguration` 回读 |
| 超时与生命周期 | `DefaultTimeout` / `Timeout` 格式（`5m`/`300s`/`1h`）、`ExpiresAt`、`StopReason` |
| 资源与磁盘 | `Resources.CPU/Memory/Storage`（1Gi/5Gi/10Gi/20Gi） |
| 幂等 | `ClientToken` 重复提交 |
| 认证 | `AuthMode`（DEFAULT/TOKEN/NONE/PUBLIC）矩阵 |
| 清理 | 每个用例结束必须回收实例与临时工具（`--ignore-not-found`） |
| 文档产出 | 每个测试例一份 `testcases/TC-XX-<name>.md`（环境、步骤、命令、实际输出、结论、问题） |

---

## 3. 需要你确认的问题

1. **阻塞项**：北京地域沙箱启动持续 `FailedOperation.Timeout`（Cloud API + E2B 均失败）。是否需要我持续重试 / 换地域 / 还是先按此现象开一个"缺陷"用例记录？
2. **"快照"到底是什么**？请给控制台入口截图或 API 名。公开文档与 SDK 里查不到 Snapshot。
3. **AgentBucket 资源**：请提供 `RoleArn`、`LibraryId`（`smh...`）、`spaceID`。
4. **AgentCFS**：现有 4 个普通 NFS CFS 能用吗？还是需要新建"Agent 文件系统"（标准型 10TiB 起 / 性能型 20TiB 起）？请确认是否已创建及 `FileSystemId`。
5. **Agent Engine 地域**：弹性部署仅上海/香港。是否把 TC-05 放到上海跑？还是只做文档/接口校验？
6. **WAA / OSWorld**：是否已有可用模板？模型 Key（OpenAI 兼容）从哪来？WAA 需要 Windows 镜像，是否已具备？
7. **E2B SDK 版本**：文档建议 `e2b==2.23.1` + `e2b_code_interpreter==2.2.1`，当前环境是 2.21.0 + 2.6.2。是否按文档对齐版本？
8. **测试文档格式**：每个测试例一个 markdown（含实际输出与截图）？还是汇总成一份？是否需要 English 版本？
9. **优先级**：7 个测试例按什么顺序做？是否先做能跑的（TC-03/TC-04），重型的（TC-06/TC-07）放后面？
