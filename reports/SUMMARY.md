# 腾讯云 AGS 新功能测试报告

| 项 | 值 |
|---|---|
| 被测产品 | 腾讯云 Agent Runtime / Agent Sandbox (AGS) |
| 主地域 | `ap-beijing`（TC-03 因地域限制改用 `ap-shanghai`） |
| AGS API 版本 | `2025-09-20`（SDK 模块 `tencentcloud.ags.v20250920`） |
| 测试日期 | 2026-09-19 |
| 执行人 | CodeBuddy（自动化脚本） |

---

## 1. 总体结论

| 测试例 | 名称 | 结论 | 检查点数 | 说明 |
|---|---|---|---|---|
| **TC-01** | 沙箱基线：TCR 镜像创建工具并启动实例 | ✅ **PASS** | 10/10 | 原阻塞问题已完全定位并解决 |
| **TC-02** | AgentBucket 持久化存储 | ✅ **PASS** | 17/17 | 含持久化、隔离、只读、负例 |
| **TC-03** | Agent Engine（弹性部署 Deployment） | ✅ **PASS** | 17/17 | 仅在 `ap-shanghai` 可用 |
| **TC-04** | AgentCFS 共享存储 | ⚠️ **PASS（1 缺陷）** | 13/14 | 发现真实缺陷：只读收紧在 CFS 上未生效 |
| TC-05 | 模板快照 Template Snapshot | ⏭ **SKIP** | — | 按决策暂缓：公开 API/SDK/文档均无 Snapshot 能力 |
| TC-06 | 沙箱快照 Sandbox Snapshot | ⏭ **SKIP** | — | 同上 |
| TC-07 | WAA 沙箱 | ⏭ **SKIP** | — | 按决策暂缓（重依赖） |
| TC-08 | OSWorld 沙箱 | ⏭ **SKIP** | — | 按决策暂缓（重依赖） |

**总计：4 个测试例，59 个检查点，58 通过 / 1 失败（真实产品缺陷）。**

### 缺陷汇总

| ID | 严重度 | 标题 | 证据 |
|---|---|---|---|
| **BUG-01** | 中高 | CFS 挂载的实例级只读收紧不生效 | `testcases/TC-04-6-*.md`：`MountOptions.ReadOnly=true` 被控制面接受并原样回读，但沙箱内挂载仍为 `rw`（virtiofs），写入成功。对照 AgentBucket 同类能力（TC-02-7）工作正常 |
| **ISSUE-01** | 低（体验） | CFS `Path` 校验延迟到启动实例阶段 | `testcases/TC-04-2-*.md`：`Path` 不存在时 `CreateSandboxTool` 仍返回 ACTIVE，直到 `StartSandboxInstance` 才报 `FailedOperation.StorageMount` |

---

## 2. 关键发现（高价值）

### 2.1 原始阻塞根因：不是地域故障，而是工具配置错误

`p.md` 中记录的原始失败是 `FailedOperation.Timeout: Sandbox creation timed out before
AGS received the provider result`。经逐项定位，真实根因是**五个独立配置问题叠加**，
与地域服务状态无关：

| # | 报错 | 根因 | 解法 |
|---|---|---|---|
| 1 | `MissingParameter.RoleArn` | `ToolType=custom` 且 `ImageRegistryType` 为 `enterprise`/`personal` 时，`RoleArn` 强制必填 | 复用 `ags-tcr-full` |
| 2 | `MissingParameter.VPCParameters` | **VPC 模式强制要求 `SecurityGroupIds`**，不只是 `SubnetIds` | 新建 `sg-p3sxc9y3` |
| 3 | `ResourceNotFound.Image` | TCR 镜像地址必须用**实例域名**而非实例 ID | 用 `euson-tcr.tencentcloudcr.com` |
| 4 | `FailedOperation.ContainerStart` | 启动命令指向 `/mnt/envd-runtime/envd`（需额外 image volume 挂载），但镜像**已内置** `/usr/bin/envd` | 改为 `/usr/bin/envd -port 49983` |
| 5 | `InvalidParameter: InstanceIds.0 类型错误` | `StartSandboxInstance` 返回 `{"Instance":{"InstanceId":...}}`，非顶层 `InstanceId` | 解析嵌套字段 |

### 2.2 文档与实现的偏差（建议反馈给产品/文档团队）

1. **`p.md` 中未提及 VPC 模式需要 `SecurityGroupIds`**
   —— 官方文档《网络模式》只写「必须同时提供 `SubnetIds` 和 `SecurityGroupIds`」，
   但实际错误信息才暴露这个是硬校验。建议在 API 文档中把两个字段都标注为必填。

2. **SDK 版本落后于 API**
   已安装的 `tencentcloud-sdk-python 3.1.63` 中 AGS 模块为 `v20250920`，**不包含**
   `CreateDeployment` / `ScalingConfiguration` / `LifecycleConfiguration` /
   `AffinityConfiguration` / `AgentBucketStorageSource` / `WAAConfiguration` /
   `OSWorldConfiguration` 等 typed model。必须用 `call_json` 透传。
   建议：升级 SDK，或在文档中明确说明需 `call_json`。

3. **`StartSandboxInstance` 返回结构未在文档中示例**
   实际返回 `Response.Instance.InstanceId`，而 `DescribeSandboxInstanceList`
   返回 `Response.InstanceSet[].InstanceId`。两者不一致，易踩坑。

4. **弹性部署地域支持与文档一致但不直观**
   实测支持：`ap-shanghai`、`ap-hongkong`；文档另列 `ap-chongqing`。
   实测**不支持**：`ap-beijing`、`ap-guangzhou`、`ap-singapore`（返回
   `UnsupportedRegion`）。而 AGS 主体的主推地域是北京，容易误以为部署也可用。

5. **Deployment 数据面域名规则容易写错**
   正确格式：`https://{port}-{deploymentId}.{region}.agents.tencentags.com`
   （注意 `.agents.` 段）。若省略该段会得到 `400 invalid sandbox id`。

6. **Persistent 模式有类型限制**
   仅 `custom` / `mobile` / `android-world` / `osworld` / `waa` 支持 `Persistent=true`；
   `code-interpreter` 会被拒：`persistent mode is only supported for custom, mobile,
   android-world, osworld and waa tool types`。

7. **`Probe.ReadyTimeoutMs` 上限为 30000ms**
   传 60000 时返回 `ReadyTimeoutMs must be at most 30000`。

8. **envd 健康检查返回 204 而非 200**
   `/health` 返回 HTTP 204，AGS 探针判定为成功。自建镜像写探针时需注意。

9. **AgentBucket 挂载点无 spaceID 时不可访问**
   即使不传 `subPath`（spaceID），实例也能启动且挂载点出现（`virtiofs`），
   但 `ls` 报 `Operation not supported`。必须传 spaceID 才能读写。
   ——这与文档描述一致，但「实例能起来、挂载点在、就是读不了」的表现容易误导排查。

10. **CFS `Path` 校验时机延迟**（ISSUE-01）
    `StorageMounts[].Path` 指向不存在的路径时，`CreateSandboxTool` **仍然成功**
    且工具状态变为 `ACTIVE`；直到 `StartSandboxInstance` 才返回
    `FailedOperation.StorageMount: storage mount path "..." not found or unreachable`。
    文档写的是「该路径必须在文件系统内已存在」，但未说明校验发生在哪个阶段。

11. **CFS 的实例级只读收紧不生效**（BUG-01，中高严重度）
    - 复现步骤：
      1. 创建工具，`StorageMounts[].ReadOnly=false`（可写）
      2. 启动实例，`MountOptions=[{"Name":"cfs-workspace","MountPath":"/mnt/cfs","ReadOnly":true}]`
    - 实际结果：控制面接受并**原样回读** `ReadOnly: true`，但沙箱内
      `mount` 显示 `... on /mnt/cfs type virtiofs (rw,relatime)`，
      `echo x > /mnt/cfs/test.txt` 返回 `WRITE-OK`。
    - 期望结果：挂载应为只读，写入应被拒绝。
    - 对照：**AgentBucket 的同类能力正常**（TC-02-7 中 `readOnly=true` 写入被正确拒绝），
      因此问题限定在 CFS 挂载路径。
    - 影响：依赖只读保护隔离多租户数据的场景存在数据被误写风险。

12. **实测：普通 NFS 型 CFS 可用于 AGS AgentCFS**
    文档（582/137338）要求使用「架构类型 = Agent 文件系统」，
    但实测普通 NFS 型 CFS（`cfs-cunkkj23`）也能正常挂载与读写。
    若确认这是有意支持，建议文档补充说明以降低用户选型成本。

### 2.3 新增发现的环境事实

- **`vpc-ovochv3a` / `subnet-pac3o08j` 有公网出口**（`curl https://www.tencentcloud.com`
  返回 200），该子网已挂 NAT。因此 VPC 模式下沙箱可直接访问公网。
- **`StartSandboxInstance` 与 E2B 是两套 ID**
  Cloud API 的 `InstanceId`（如 `ydkd7...`）与 E2B 的 `sandbox_id`
  （如 `nfteo...`）不同，需通过 `AcquireSandboxInstanceToken` 或 SDK 关联。
- **CFS 现有 4 个实例均为普通 NFS**，非 Agent 文件系统，无法直接用于 AgentCFS。

---

## 3. 各测试例详情

### TC-01 沙箱基线（PASS）

**目的**：打通「创建工具 → ACTIVE → 启动实例 → RUNNING → 数据面执行 → 回收」最小闭环。

| # | 步骤 | 结论 |
|---|---|---|
| 1 | CreateSandboxTool（TCR 镜像 + VPC 模式） | ✅ |
| 2 | 等待工具 ACTIVE | ✅ |
| 3 | 镜像 digest 已解析 | ✅ |
| 4 | StartSandboxInstance | ✅ |
| 5 | 等待实例 RUNNING | ✅ |
| 6 | E2B 连接沙箱实例 | ✅ |
| 7 | 数据面执行 shell 命令 | ✅ |
| 8 | 文件 API 读写 | ✅ |
| 9 | VPC 出网行为记录 | ✅（实测可出网） |
| 10 | 停止实例并确认回收 | ✅ |

产物：`scripts/tc01_baseline.py`、`reports/TC-01-VPC.md`、`testcases/TC-01-*.md`

### TC-02 AgentBucket（PASS）

**目的**：验证基于 SMH 的沙箱持久化存储。

| # | 用例 | 结论 | 关键验证点 |
|---|---|---|---|
| TC-02-1 | 创建带 AgentBucket 的 code-interpreter 工具 | ✅ | 只传 `LibraryId`、不传 `SpaceId`；回查一致 |
| TC-02-2 | 负例：custom 缺 Probe | ✅ | 返回 `MissingParameter` |
| TC-02-3 | E2B 启动 + `subPath=spaceID` + `mountPath` 覆盖 | ✅ | 挂载点可写 |
| TC-02-4 | 文件 API 四件套 write/read/exists/list | ✅ | 全部可用 |
| TC-02-5 | **跨实例持久化** | ✅ | kill 后新实例（不同 `sandbox_id`）读回旧数据 |
| TC-02-6 | 不同 `subPath` 数据隔离 | ✅ | 看不到彼此数据 |
| TC-02-7 | 实例级只读收紧 | ✅ | `readOnly=true` 后写入被拒 |
| TC-02-8 | 负例：不存在的 spaceID | ✅ | 实例可启动但目录访问报 `No such file or directory`（与文档一致） |

**使用资源**（用户提供）：
- SMH Library：`smh3qv6cmcoscm4i`（`cedricbwang-agentbucket`，`IsMultiSpace=true`、
  `BucketRegion=ap-beijing`）—— 满足 `subPath=spaceID` 模式对多空间的要求
- spaceID：`space3ly9r9ni7fhju`（该库共 2 个空间，取第一个）
- 获取方式：`GET /api/v1/token?library_id=<lib>&library_secret=<secret>&grant=admin`
  → `GET /api/v1/space/{lib}/list?access_token=<token>`

**结论**：8 个用例 17 个检查点全部通过，AgentBucket 功能在用户自建媒体库上表现正常，
包括跨实例持久化（TC-02-5）与实例级只读收紧（TC-02-7）。

产物：`scripts/tc02_agentbucket.py`、`reports/TC-02.md`、8 个用例文档

### TC-03 Agent Engine 弹性部署（PASS）

**目的**：验证面向在线服务场景的长期托管资源（Deployment）。

| # | 用例 | 结论 | 关键验证点 |
|---|---|---|---|
| TC-03-1 | 地域支持性探测 | ✅ | `ap-shanghai`/`ap-hongkong` 支持；北京不支持 |
| TC-03-2 | 创建 Persistent 工具 | ✅ | code-interpreter 被拒；custom 成功 |
| TC-03-3 | CreateDeployment → ACTIVE | ✅ | 伸缩/生命周期/亲和默认值已物化 |
| TC-03-4 | AcquireDeploymentToken + 数据面访问 | ✅ | HTTP 200，返回 httpbin JSON；无 Token 被拒 |
| TC-03-4b | **弹性部署按需拉起实例** | ✅ | 0→1 自动扩容，工具下出现 RUNNING 实例 |
| TC-03-5 | ModifyDeployment | ✅ | 伸缩与生命周期更新生效 |
| TC-03-6 | DescribeDeployment / List | ✅ | 单查与列表均命中 |
| TC-03-7 | 负例：绑定非 Persistent 工具 | ✅ | 被拒 |
| TC-03-8 | 异步删除 | ✅ | 删除最终生效 |

产物：`scripts/tc03_agent_engine.py`、`reports/TC-03.md`、9 个用例文档

### TC-04 AgentCFS 共享存储（PASS，含 1 缺陷）

**目的**：验证基于 CFS 的沙箱共享存储（含跨实例持久化与目录隔离）。

> **重要发现**：文档要求「架构类型 = Agent 文件系统」才能使用 AgentCFS，
> 但**实测普通 NFS 型 CFS（`cfs-cunkkj23`）也能被 AGS 正常接受并挂载读写**，
> 无需额外创建 AgentCFS 或承担 10TiB/20TiB 起购成本。

| # | 用例 | 结论 | 关键验证点 |
|---|---|---|---|
| TC-04-1 | 创建挂 CFS 的 custom 工具 | ✅ | 回查 `FileSystemId` / `Path` 一致 |
| TC-04-2 | 负例：`Path` 不存在 | ✅（记录特性） | 工具仍 ACTIVE，错误延迟到启动实例才暴露 |
| TC-04-3 | 启动实例 + 挂载读写（`user=root`） | ✅ | 挂载为 `virtiofs`，可建目录/写文件 |
| TC-04-4 | **跨实例持久化** | ✅ | kill 后新实例读回旧数据 |
| TC-04-5 | 不同 `subPath` 目录隔离 | ✅ | 隔离生效 |
| TC-04-6 | 实例级只读收紧 | ❌ **FAIL** | **真实缺陷**：`ReadOnly=true` 被接受但挂载仍 `rw` |
| TC-04-7 | `MountPath` 覆盖默认路径 | ✅ | `/mnt/cfs` → `/mnt/cfs-alt` 生效 |

**复用资源**：`cfs-cunkkj23`（`jw-test`，普通 NFS，ap-beijing-6）

产物：`scripts/tc04_agentcfs.py`、`reports/TC-04.md`、7 个用例文档

---

## 4. 测试资产清单

```
ags-newfeature/
├── README.md                         # ★ 项目入口
├── docs/
│   ├── requirements/                 # 原始需求
│   │   ├── p.md
│   │   └── agentbucket.md
│   ├── design/
│   │   ├── test-plan.md              # ★ 测试方案（含环境摸底与踩坑记录）
│   │   └── decisions.md              # 决策记录
│   └── guides/
│       └── agentbucket-agentcfs-setup.md   # 存储资源创建指导
├── scripts/
│   ├── check_readiness.py            # 环境就绪检查
│   ├── tc01_baseline.py              # TC-01 沙箱基线
│   ├── tc02_agentbucket.py           # TC-02 AgentBucket（8 用例）
│   ├── tc03_agent_engine.py          # TC-03 Agent Engine（9 用例）
│   └── tc04_agentcfs.py              # TC-04 AgentCFS（7 用例）
├── lib/
│   ├── config.py                     # 配置与环境变量
│   ├── ags_api.py                    # 腾讯云 AGS 控制面封装
│   ├── e2b_api.py                    # E2B 数据面封装
│   ├── recorder.py                   # 测试记录与文档生成
│   └── cleanup.py                    # 资源自动回收
├── reports/                          # 测试报告
│   ├── SUMMARY.md                    # ★ 总报告
│   ├── TC-01-VPC.md
│   ├── TC-02.md
│   ├── TC-03.md
│   └── TC-04.md
└── testcases/                        # 按测试例生成的标准文档（24 份）
```

### 复现方式

```bash
cd /root/ags
python3 scripts/tc01_baseline.py                                   # 北京，VPC
python3 scripts/tc02_agentbucket.py                                # 北京，VPC
AGS_TARGET_REGION=ap-shanghai python3 scripts/tc03_agent_engine.py # 上海
python3 scripts/tc04_agentcfs.py                                   # 北京，VPC
```

> 所有脚本内置 `CleanupRegistry`，测试结束自动回收实例与工具；
> 排障时可用 `AGS_KEEP_RESOURCES=1` 保留资源。

---

## 5. 遗留事项

| 项 | 需要谁 | 说明 |
|---|---|---|
| **BUG-01 修复** | AGS 产品团队 | CFS `MountOptions.ReadOnly=true` 未在沙箱内生效（证据见 `reports/TC-04.md`） |
| **ISSUE-01 改进** | AGS 产品团队 | CFS `Path` 校验建议提前到 `CreateSandboxTool` 阶段 |
| 快照功能范围澄清 | 产品/用户 | 公开 API/SDK/文档均无 Snapshot，需明确是什么功能 |
| WAA / OSWorld | 用户 | 需 WAA 兼容模板 / OSWorld 兼容模板 + 模型 Key |
| SDK 升级建议 | 产品 | 建议发布支持 Deployment / AgentBucket 的 typed model |

> **关于 AgentCFS**：原计划需用户新建「Agent 文件系统」（10TiB/20TiB 起），
> 实测**普通 NFS 型 CFS 可直接使用**，该笔开销可以省去。

---

## 6. 环境凭据与资源（脱敏说明）

敏感信息（AK/SK、TCR token、E2B API Key、SMH LibrarySecret）均只存在于
`/root/ags/.env`，已在 `.gitignore` 中排除。`docs/design/decisions.md` 中含 TCR token，
如需共享报告请注意脱敏。
