# AGS 新功能测试

腾讯云 Agent Runtime / Agent Sandbox（AGS）新功能的测试工程：测试方案、可复现脚本、逐用例测试文档与缺陷记录。

- 主地域：`ap-beijing`（弹性部署因地域限制使用 `ap-shanghai`）
- AGS API 版本：`2025-09-20`
- 测试日期：2026-09-19

---

## 测试结果总览

| 测试例 | 名称 | 结论 | 检查点 |
|---|---|---|---|
| [TC-01](testcases/) | 沙箱基线：TCR 镜像创建工具并启动实例 | ✅ PASS | 10/10 |
| [TC-02](testcases/) | AgentBucket 持久化存储 | ✅ PASS | 17/17 |
| [TC-03](testcases/) | Agent Engine（弹性部署 Deployment） | ✅ PASS | 17/17 |
| [TC-04](testcases/) | AgentCFS 共享存储 | ⚠️ PASS | 13/14 |
| TC-05 | 模板快照 Template Snapshot | ⏭ 暂缓 | — |
| TC-06 | 沙箱快照 Sandbox Snapshot | ⏭ 暂缓 | — |
| TC-07 | WAA 沙箱 | ⏭ 暂缓 | — |
| TC-08 | OSWorld 沙箱 | ⏭ 暂缓 | — |

**合计：4 个测试例，59 个检查点，58 通过 / 1 失败（真实产品缺陷）。**

完整结论、关键发现与文档偏差清单见 **[reports/SUMMARY.md](reports/SUMMARY.md)**。

---

## 目录结构

```
.
├── README.md
├── docs/
│   ├── requirements/          # 原始需求文档
│   │   ├── p.md               # 测试目标与测试例清单
│   │   └── agentbucket.md     # AgentBucket 官方手册（存档）
│   ├── design/
│   │   ├── docs/design/test-plan.md       # 测试方案（含环境摸底、踩坑记录、用例设计）
│   │   └── decisions.md       # 与用户确认的决策记录
│   └── guides/
│       └── agentbucket-agentcfs-setup.md   # 存储资源创建指导
├── scripts/
│   ├── check_readiness.py     # 环境就绪检查（镜像 / CFS / 端到端冒烟）
│   ├── tc01_baseline.py       # TC-01 沙箱基线
│   ├── tc02_agentbucket.py    # TC-02 AgentBucket（8 用例）
│   ├── tc03_agent_engine.py   # TC-03 Agent Engine（9 用例）
│   └── tc04_agentcfs.py       # TC-04 AgentCFS（7 用例）
├── lib/                       # 公共库
│   ├── config.py              # 配置与环境变量
│   ├── ags_api.py             # 腾讯云 AGS 控制面封装
│   ├── e2b_api.py             # E2B 数据面封装
│   ├── recorder.py            # 测试记录与文档生成
│   └── cleanup.py             # 资源自动回收
├── reports/                   # 测试报告
│   ├── SUMMARY.md             # ★ 总报告
│   ├── TC-01-VPC.md
│   ├── TC-02.md
│   ├── TC-03.md
│   └── TC-04.md
├── testcases/                 # 按测试例生成的标准文档（24 份）
├── .env.example               # 环境变量模板
└── .gitignore
```

---

## 快速开始

### 1. 准备环境

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install tencentcloud-sdk-python 'e2b-code-interpreter==2.6.2' 'e2b==2.21.0' requests
```

### 2. 配置凭证

```bash
cp .env.example .env
# 编辑 .env，填入腾讯云 AK/SK、E2B API Key、被测资源 ID
```

关键变量：

| 变量 | 说明 |
|---|---|
| `TENCENTCLOUD_SECRET_ID` / `_SECRET_KEY` | 腾讯云 API 密钥 |
| `TENCENTCLOUD_REGION` | 默认 `ap-beijing` |
| `E2B_API_KEY` / `E2B_DOMAIN` | E2B 数据面 |
| `AGS_ROLE_ARN` | CAM 角色（拉镜像 / 访问存储） |
| `AGS_VPC_ID` / `AGS_SUBNET_ID` / `AGS_SECURITY_GROUP_ID` | VPC 模式必需 |
| `AGT_IMAGE` / `AGT_ENVD_PATH` | 被测沙箱镜像及其 envd 路径 |
| `AGENTBUCKET_LIBRARY_ID` / `_SPACE_ID` / `_LIBRARY_SECRET` | AgentBucket |
| `AGENTCFS_FILE_SYSTEM_ID` / `AGENTCFS_PATH` | AgentCFS |

### 3. 就绪检查

```bash
python3 scripts/check_readiness.py        # 检查镜像 tag、envd、CFS 挂载点
python3 scripts/check_readiness.py --e2e  # 额外做端到端冒烟
```

### 4. 执行测试

```bash
python3 scripts/tc01_baseline.py                                    # 北京，VPC
python3 scripts/tc02_agentbucket.py                                 # 北京，VPC
python3 scripts/tc03_agent_engine.py                                # 上海，PUBLIC
python3 scripts/tc04_agentcfs.py                                    # 北京，VPC
```

> 所有脚本内置 `CleanupRegistry`，测试结束自动回收实例与工具。
> 排障时设 `AGS_KEEP_RESOURCES=1` 保留资源；`AGS_TEST_PREFIX` 可改资源名前缀。

---

## 关键发现

### 1. 沙箱启动失败的根因（5 个配置问题叠加）

原始失败现象是 `FailedOperation.Timeout`，容易被误判为地域故障。逐项定位后：

| # | 报错 | 根因 | 解法 |
|---|---|---|---|
| 1 | `MissingParameter.RoleArn` | `ToolType=custom` 且 `ImageRegistryType` 为 `enterprise`/`personal` 时 `RoleArn` 必填 | 配置 CAM 角色 |
| 2 | `MissingParameter.VPCParameters` | **VPC 模式强制要求 `SecurityGroupIds`**，不只是 `SubnetIds` | 补安全组 |
| 3 | `ResourceNotFound.Image` | TCR 镜像地址必须用**实例域名**而非实例 ID | 用 `<name>.tencentcloudcr.com` |
| 4 | `FailedOperation.ContainerStart` | 启动命令指向的 envd 路径不存在（镜像内已有 `/usr/bin/envd`） | 修正启动命令 |
| 5 | `InvalidParameter: InstanceIds.0 类型错误` | `StartSandboxInstance` 返回 `{"Instance":{"InstanceId":...}}` 嵌套结构 | 解析嵌套字段 |

### 2. 缺陷 BUG-01：CFS 实例级只读收紧不生效（中高）

- **复现**：工具级 `ReadOnly=false`，实例级 `MountOptions.ReadOnly=true`
- **实际**：控制面接受并原样回读 `true`，但沙箱内挂载仍是 `rw`，写入成功
- **期望**：挂载只读，写入被拒绝
- **对照**：AgentBucket 的同类能力**正常**，问题限定在 CFS 路径
- **影响**：依赖只读保护隔离多租户数据的场景存在数据误写风险

详见 [reports/TC-04.md](reports/TC-04.md) 与 `testcases/TC-04-6-*.md`。

### 3. 其他值得注意的行为

- **弹性部署仅支持 `ap-shanghai` / `ap-hongkong`**；`ap-beijing`、`ap-guangzhou`、`ap-singapore` 返回 `UnsupportedRegion`
- **Persistent 工具有类型限制**：仅 `custom` / `mobile` / `android-world` / `osworld` / `waa` 支持，`code-interpreter` 会被拒
- **Deployment 数据面域名含 `.agents.` 段**：`https://{port}-{dpl-id}.{region}.agents.tencentags.com`，写错会得到 `400 invalid sandbox id`
- **CFS `Path` 校验延迟**：`Path` 不存在时 `CreateSandboxTool` 仍返回 ACTIVE，直到 `StartSandboxInstance` 才报错
- **envd `/health` 返回 204**（非 200），AGS 探针判定为成功
- **普通 NFS 型 CFS 可用于 AGS**：文档要求「Agent 文件系统」，但实测普通 NFS 也能正常挂载读写

完整的 12 条文档与实现偏差见 [reports/SUMMARY.md](reports/SUMMARY.md)。

---

## 已配置的被测资源

| 资源 | 值 | 状态 |
|---|---|---|
| AgentBucket 媒体库 | `smh3qv6cmcoscm4i`（`cedricbwang-agentbucket`，多空间） | ✅ TC-02 已通过 |
| AgentBucket 空间 | `space3ly9r9ni7fhju` | ✅ |
| AgentCFS | `cfs-45a313f3e`（TURBO 型，挂载点已建） | ✅ TC-04 已通过 |
| 被测镜像 | `euson-tcr.tencentcloudcr.com/cedricbwang/test:v1` | ⏸ 仓库为空 |
| 已验证镜像 | `euson-tcr.tencentcloudcr.com/sandbox/sandbox:v1` | ✅ TC-01 已通过 |
| 备用 CFS | `cfs-cunkkj23`（NFS） | ✅ 早期验证 |

### 待办

| 项 | 说明 |
|---|---|
| 推送被测镜像 | `cedricbwang/test:v1` 仓库当前 **0 个 tag**；该 namespace 为私有，还需确认 `ags-tcr-full` 角色有拉取权限。TC-01/TC-04 暂用已验证镜像 `sandbox/sandbox:v1`，镜像就绪后需复测 |

用 `scripts/check_readiness.py` 可随时确认：

```bash
python3 scripts/check_readiness.py        # 只检查
python3 scripts/check_readiness.py --e2e  # 检查 + 端到端冒烟
```

---

## 说明

- 本仓库所有测试资源均已回收（北京 / 上海两地残留数为 0）。
- 敏感信息（AK/SK、TCR token、E2B API Key、SMH LibrarySecret）只存在于本地 `.env`，已在 `.gitignore` 中排除。
- 测试脚本使用 `call_json` 透传调用云 API，因为当前 `tencentcloud-sdk-python` 尚未发布
  `CreateDeployment` / `ScalingConfiguration` / `AgentBucketStorageSource` 等 typed model。
