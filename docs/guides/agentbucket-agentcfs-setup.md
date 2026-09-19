# AgentBucket / AgentCFS 资源创建指导

> 用途：为 TC-02（AgentBucket）和 TC-03（AgentCFS）准备被测资源。
> 我已先做了排查，**AgentBucket 的大部分资源已经具备**，你只需补一个 spaceID。
> AgentCFS 需要你新建文件系统。

---

## 一、AgentBucket —— ✅ 已就绪

### 1.1 状态（2026-09-19 更新）

| 依赖项 | 状态 | 说明 |
|---|---|---|
| SMH Library | ✅ 用户提供 | `smh3qv6cmcoscm4i`（`cedricbwang-agentbucket`） |
| Library 多空间 | ✅ `IsMultiSpace=true` | `subPath=spaceID` 模式的前提 |
| LibrarySecret | ✅ 已配置 | 已写入本地 `.env`（`AGENTBUCKET_LIBRARY_SECRET`） |
| spaceID | ✅ 已获得 | `space3ly9r9ni7fhju`（该库共 2 个空间，取第一个） |
| CAM Role | ✅ 已有 | `ags-tcr-full`，信任 `ags.cloud.tencent.com`，含 `AdministratorAccess` |
| VPC / 安全组 | ✅ 已有 | `vpc-ovochv3a` / `subnet-pac3o08j` / `sg-p3sxc9y3` |
| 镜像 | ✅ 已有 | `euson-tcr.tencentcloudcr.com/sandbox/sandbox:v1` |

**TC-02 全部 8 个用例已用该库执行通过（17/17 检查点）。**

### 1.2 如何获得 spaceID

SMH 的 spaceID 可以通过业务面 API 自动获取（无需控制台操作）：

```bash
# 1) 用 LibrarySecret 换 AccessToken
curl "https://{LibraryId}.ap-beijing.api.tencentsmh.cn/api/v1/token?\
library_id={LibraryId}&library_secret={LibrarySecret}&grant=admin&period=3600"

# 2) 列出该库的所有空间
curl "https://{LibraryId}.ap-beijing.api.tencentsmh.cn/api/v1/space/{LibraryId}/list?\
access_token={AccessToken}&limit=100"
```

响应中的 `list[].spaceId` 即为可传给 `metadata.x-mounts[].subPath` 的 spaceID。

也可在 [SMH 控制台](https://console.cloud.tencent.com/smh) 的「空间管理」页面查看。

### 1.3 当前配置（已在 `.env` 中）

```bash
AGENTBUCKET_LIBRARY_ID=smh3qv6cmcoscm4i
AGENTBUCKET_SPACE_ID=space3ly9r9ni7fhju
AGENTBUCKET_LIBRARY_SECRET=<见本地 .env，勿提交>
```

### 1.4 账号下其他可用的 SMH Library（备查）

| LibraryId | 名称 | 多空间 | 备注 |
|---|---|---|---|
| `smh3qv6cmcoscm4i` | cedricbwang-agentbucket | ✅ True | **本次测试使用** |
| `smh3cy4mpur43m1j` | FredTest | ❌ False | 单空间，不适合 spaceID 模式 |
| `smh223rot7x8yvmc` | ClawPro-admin-1258272081-0 | ✅ True | |
| `smh2ws7gv815z8r3` | leotestforkimi | ✅ True | 早期探测用 |

### 1.5 若需新建 Role（当前不必要）

现有 `ags-tcr-full` 已关联 `AdministratorAccess`，SMH 权限已覆盖。若要最小权限化：

1. [CAM 角色控制台](https://console.cloud.tencent.com/cam/role) → 「新建角色」→ 「腾讯云服务」
2. 角色载体选择 **Agent 沙箱服务（ags）**
3. 信任策略：
   ```json
   {
     "version": "2.0",
     "statement": [
       {"action": "name/sts:AssumeRole", "effect": "allow",
        "principal": {"service": ["ags.cloud.tencent.com"]}}
     ]
   }
   ```
4. 关联预设策略 **`QcloudSMHFullAccess`**（必须）；镜像来自 TCR 时另加 `QcloudTCRFullAccess`
5. ARN 格式：`qcs::cam::uin/<UIN>:roleName/<角色名>`

---

## 二、AgentCFS —— ⏸ 待创建挂载点

### 2.1 排查结论（我已验证）

现有 4 个 CFS 文件系统：

| FileSystemId | 名称 | 协议 | 可用区 |
|---|---|---|---|
| `cfs-qr3xtqol` | cfs_leony | NFS | ap-beijing-6 |
| `cfs-093u0f81` | jw-cfs-tione | NFS | ap-beijing-6 |
| `cfs-2zzozjy7` | jw-cfs | NFS | ap-beijing-6 |
| `cfs-cunkkj23` | jw-test | NFS | ap-beijing-6 |

**全部是普通 NFS，不是 AgentCFS。**

### 2.2 两种可行路径（2026-09-19 更新）

**路径 A（已验证可用，无需额外开销）**：普通 NFS 型 CFS
实测 `cfs-cunkkj23`（NFS）可直接被 AGS 接受并正常挂载读写，TC-04 全部用例
（挂载 / 读写 / 跨实例持久化 / subPath 隔离 / MountPath 覆盖）均已通过。

**路径 B（用户指定的专用 AgentCFS）**：`cfs-45a313f3e`
- 类型：`protocol=TURBO`、`storage=TP`、zone `ap-beijing-6`、名称 `cedricbwang`
- **当前无挂载点**，AGS 报 `no mount targets found for CFS`
- ⚠️ CFS 的 PaaS API **不提供创建挂载点的接口**（全套 54 个 action 中无 `CreateMountTarget`），
  只能在控制台操作

### 2.3 如何为 `cfs-45a313f3e` 创建挂载点

1. 打开 [文件存储控制台](https://console.cloud.tencent.com/cfs)
2. 找到 `cfs-45a313f3e`（名称 `cedricbwang`）
3. 进入「挂载点」页签 → 「添加挂载点」
4. 选择**与沙箱互通的 VPC**，推荐：
   - VPC：`vpc-ovochv3a`
   - 子网：`subnet-pac3o08j`（ap-beijing-8）
   - 权限组：默认放通
5. 创建后可用 `python3 scripts/check_readiness.py` 确认

> 注意：TURBO 型 CFS 可能对可用区/VPC 有额外约束，若创建失败请按控制台提示调整。

> 现有文件系统中 `cfs-cunkkj23`（jw-test）容量为 0 且看起来是测试用途。
> 如果你希望避免新建成本，可以让我先**试挂一个普通 NFS**看 AGS 是否接受 —— 
> 但按官方文档，应该只有 Agent 文件系统可用。

### 2.4（可选）新建 AgentCFS 的完整步骤

1. 打开 [文件存储控制台](https://console.cloud.tencent.com/cfs) → 单击「新建」

2. 配置基础信息：

   | 配置项 | 选择 |
   |---|---|
   | 文件系统名称 | `agstest-cfs` |
   | 地域 / 可用区 | **北京（ap-beijing）**，可用区选 **北京八区**（与 `subnet-pac3o08j` 的 `ap-beijing-8` 一致） |
   | **架构类型** | **Agent 文件系统** |
   | 存储类型 | **Agent CFS 标准型**（延迟不敏感，起步 10TiB）<br>或 **Agent CFS 性能型**（延迟敏感，起步 20TiB） |
   | 存储量 | 按起步容量设置 |
   | 自动扩容策略 | 可选，建议开启 |
   | 加密 / 标签 | 按需 |

   > ⚠️ **成本提示**：AgentCFS 起步容量较大（标准型 10TiB / 性能型 20TiB）。
   > 如果只是做功能验证，请评估费用后决定是否创建。
   > **如果你希望避免这笔开销，告诉我，我可以把 TC-03 降级为"接口与配置符合性验证"（不实际创建文件系统）。**

3. 确认费用 → 「立即创建」

4. 创建完成后，在文件系统列表中记录 **文件系统 ID**（形如 `cfs-xxxxxxxx`）

5. **在 CFS 内创建至少一个目录**（重要）：
   - `StorageMounts[].Path` 指向的路径**必须在文件系统内已存在**，否则创建模板会报错
   - 最简单的做法：直接用根目录 `/`
   - 或者用一台 CVM 挂载后 `mkdir /agstest`，然后 `Path` 填 `/agstest`

**你需要回填给我：**

```
AGENTCFS_FILE_SYSTEM_ID=cfs-xxxxxxxx
AGENTCFS_PATH=/            # 或 /agstest
```

### 2.5 权限

若复用 `ags-tcr-full`（已含 `AdministratorAccess`），CFS 权限已覆盖，**无需额外配置**。

若使用自建最小权限 Role，需关联 **`QcloudCFSFullAccess`**。

> 注意官方文档说明：**仅配置 CFS 且沙箱类型不是 Custom 时可不传 `RoleArn`；Custom 类型仍需 `RoleArn`。**

---

## 三、当前 `.env` 配置

```bash
# AgentBucket —— 已就绪，TC-02 已通过
AGS_ROLE_ARN=qcs::cam::uin/100008634787:roleName/ags-tcr-full
AGENTBUCKET_LIBRARY_ID=smh3qv6cmcoscm4i
AGENTBUCKET_SPACE_ID=space3ly9r9ni7fhju
AGENTBUCKET_LIBRARY_SECRET=<见本地 .env>

# AgentCFS —— 已指定，待创建挂载点
AGENTCFS_FILE_SYSTEM_ID=cfs-45a313f3e
AGENTCFS_PATH=/

# 被测镜像 —— 待推送
AGT_IMAGE=euson-tcr.tencentcloudcr.com/cedricbwang/test:v1
```

就绪后用 `python3 scripts/check_readiness.py --e2e` 验证。

---

## 四、当前已具备的环境（无需你操作，供参考）

| 资源 | 值 |
|---|---|
| Region | `ap-beijing` |
| E2B Domain | `ap-beijing.tencentags.com` |
| E2B API Key | 已配置（`ark_...`） |
| VPC | `vpc-ovochv3a` |
| Subnet | `subnet-pac3o08j`（ap-beijing-8, 172.21.128.0/20，**已挂 NAT 可出网**） |
| Security Group | `sg-p3sxc9y3`（`agstest-sg`，放通全出入站）**← 我新建的** |
| CAM Role | `ags-tcr-full`（`AdministratorAccess` + `QcloudTCRFullAccess`，信任 `ags.cloud.tencent.com`） |
| 已验证镜像 | `euson-tcr.tencentcloudcr.com/sandbox/sandbox:v1`（1.79GB，内置 `/usr/bin/envd`，Python 3.12.13） |
| 待验证镜像 | `euson-tcr.tencentcloudcr.com/cedricbwang/test:v1`（用户提供，仓库当前为空） |
| 已验证 CFS | `cfs-cunkkj23`（NFS，TC-04 已通过） |
| 待验证 CFS | `cfs-45a313f3e`（TURBO，缺挂载点） |
| envd 启动命令 | `/usr/bin/envd -port 49983`（健康检查 `/health` 返回 204） |
| TCR | 实例 `tcr-mvlaq1sq`，域名 `euson-tcr.tencentcloudcr.com` |
