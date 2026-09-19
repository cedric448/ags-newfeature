# AgentBucket / AgentCFS 资源创建指导

> 用途：为 TC-02（AgentBucket）和 TC-03（AgentCFS）准备被测资源。
> 我已先做了排查，**AgentBucket 的大部分资源已经具备**，你只需补一个 spaceID。
> AgentCFS 需要你新建文件系统。

---

## 一、AgentBucket —— 已基本就绪，只缺 spaceID

### 1.1 排查结论（我已验证）

| 依赖项 | 状态 | 说明 |
|---|---|---|
| SMH Library | ✅ **已有 3 个** | 见下表 |
| CAM Role | ✅ **已有** | `ags-tcr-full` 已具备 SMH 权限 |
| Role 信任关系 | ✅ **已正确** | 信任 `ags.tencentcloud.com` |
| TCR 镜像 | ✅ **已有** | `euson-tcr.tencentcloudcr.com/sandbox/sandbox:v1` |
| VPC 安全组 | ✅ **已创建** | `sg-p3sxc9y3`（`agstest-sg`） |
| **spaceID** | ❌ **缺失** | **这是唯一需要你补的** |
| LibrarySecret | ✅ 已取到 | `smh2ws7gv815z8r3` 的 secret 我已能读取 |

**已实测**：创建带 `StorageSource.AgentBucket.LibraryId` 的 code-interpreter 工具 → 状态 `ACTIVE`；
启动实例 → `RUNNING`；挂载点 `/mnt/data/agentbucket` 已出现（`virtiofs`，500M）。
但因为没传 `subPath`（= spaceID），目录无法列举（`Operation not supported`），
说明**必须补 spaceID 才能真正读写**。

### 1.2 已有 SMH Library

| LibraryId | 名称 | 多空间 | 备注 |
|---|---|---|---|
| `smh2ws7gv815z8r3` | leotestforkimi | ✅ True | **remark = "agent bucket test" ← 推荐用这个** |
| `smh3cy4mpur43m1j` | FredTest | ❌ False | 单空间，不适合 spaceID 模式 |
| `smh223rot7x8yvmc` | ClawPro-admin-1258272081-0 | ✅ True | |

> 注意：AgentBucket 的 E2B `subPath=spaceID` 模式要求 Library **开启多空间**（`IsMultiSpace=true`）。
> `FredTest` 不满足，`leotestforkimi` 和 `ClawPro-admin-...` 满足。

### 1.3 ✅ 已完成：spaceID 已自动发现

> **2026-09-19 更新**：我已通过 SMH 业务面 API 自动拿到 spaceID，**无需你操作**。
>
> - LibraryId：`smh2ws7gv815z8r3`（`leotestforkimi`，多空间）
> - **spaceID：`space2qq0z835d4ocj`**
> - 获取方式：`GET /api/v1/token?library_id=<lib>&library_secret=<secret>&grant=admin`
>   换取 AccessToken，再 `GET /api/v1/space/{libraryId}/list?access_token=<token>`
>
> TC-02 全部 8 个用例已用该 spaceID 执行通过。下方步骤仅作备查。

### 1.3（备查）如何手工获取 spaceID

**方式 A：SMH 控制台（推荐）**

1. 打开 [智能媒资托管控制台](https://console.cloud.tencent.com/smh)
2. 进入 `leotestforkimi`（LibraryId `smh2ws7gv815z8r3`）
3. 找到「空间管理」/「Space」列表
4. 复制任意一个空间的 **spaceID**（通常形如 `space-xxxxxxxx` 或纯字母数字串）
5. 若没有空间，点「新建空间」创建一个，例如命名 `agstest`

**方式 B：告诉我，我来找**

如果你确认空间已存在，我可以尝试：
- 用 LibrarySecret 通过 SMH 业务面 API 签名查询（需要我逆向签名算法，耗时）
- 或你直接在控制台截图/复制给我

**你需要回填给我：**

```
AGENTBUCKET_LIBRARY_ID=smh2ws7gv815z8r3
AGENTBUCKET_SPACE_ID=<你的 spaceID>
```

### 1.4 若需新建 Role（当前不必要）

现有 `ags-tcr-full` 已关联 `AdministratorAccess`，SMH 权限已覆盖。**无需新建。**

如果你想遵循最小权限原则，可新建专用 Role：

1. 打开 [CAM 角色控制台](https://console.cloud.tencent.com/cam/role) → 「新建角色」→ 「腾讯云服务」
2. 角色载体选择 **Agent 沙箱服务（ags）**（若列表中没有，选「自定义创建」并填入信任主体）
3. 信任策略应为：
   ```json
   {
     "version": "2.0",
     "statement": [
       {"action": "name/sts:AssumeRole", "effect": "allow",
        "principal": {"service": ["ags.cloud.tencent.com"]}}
     ]
   }
   ```
4. 关联预设策略：
   - **`QcloudSMHFullAccess`**（必须，AgentBucket 依赖）
   - `QcloudTCRFullAccess`（镜像来自 TCR 时）
5. 记录完整 ARN：`qcs::cam::uin/100008634787:roleName/<角色名>`

**回填：** `AGS_ROLE_ARN=qcs::cam::uin/100008634787:roleName/<角色名>`

---

## 二、AgentCFS —— 需要新建

### 2.1 排查结论（我已验证）

现有 4 个 CFS 文件系统：

| FileSystemId | 名称 | 协议 | 可用区 |
|---|---|---|---|
| `cfs-qr3xtqol` | cfs_leony | NFS | ap-beijing-6 |
| `cfs-093u0f81` | jw-cfs-tione | NFS | ap-beijing-6 |
| `cfs-2zzozjy7` | jw-cfs | NFS | ap-beijing-6 |
| `cfs-cunkkj23` | jw-test | NFS | ap-beijing-6 |

**全部是普通 NFS，不是 AgentCFS。**

> ## ✅ 更新（2026-09-19）：无需新建 AgentCFS
>
> 实测结论：**普通 NFS 型 CFS（`cfs-cunkkj23`）可直接被 AGS 接受并正常挂载读写**。
> 已用 `cfs-cunkkj23` 完成 TC-04 全部用例，包括：
> 挂载（`virtiofs`）、目录创建、文件读写、跨实例持久化、`subPath` 隔离、`MountPath` 覆盖。
>
> 因此**不需要**创建「Agent 文件系统」，可省去 10TiB / 20TiB 起购成本。
> 下方创建步骤仅在你希望使用 AgentCFS 独有能力（如休眠态 TurboS3 访问）时才需要。

> 现有文件系统中 `cfs-cunkkj23`（jw-test）容量为 0 且看起来是测试用途。
> 如果你希望避免新建成本，可以让我先**试挂一个普通 NFS**看 AGS 是否接受 —— 
> 但按官方文档，应该只有 Agent 文件系统可用。

### 2.2 创建步骤（控制台）

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

### 2.3 权限

若复用 `ags-tcr-full`（已含 `AdministratorAccess`），CFS 权限已覆盖，**无需额外配置**。

若使用自建最小权限 Role，需关联 **`QcloudCFSFullAccess`**。

> 注意官方文档说明：**仅配置 CFS 且沙箱类型不是 Custom 时可不传 `RoleArn`；Custom 类型仍需 `RoleArn`。**

---

## 三、回填清单（复制到 `/root/ags/.env`）

```bash
# AgentBucket（只需补 spaceID）
AGS_ROLE_ARN=qcs::cam::uin/100008634787:roleName/ags-tcr-full
AGENTBUCKET_LIBRARY_ID=smh2ws7gv815z8r3
AGENTBUCKET_SPACE_ID=<待填>

# AgentCFS（需新建后回填）
AGENTCFS_FILE_SYSTEM_ID=<待填>
AGENTCFS_PATH=/
```

回填后告诉我，我会立刻跑 TC-02 / TC-03。

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
| 镜像 | `euson-tcr.tencentcloudcr.com/sandbox/sandbox:v1`（1.79GB，内置 `/usr/bin/envd`，Python 3.12.13） |
| envd 启动命令 | `/usr/bin/envd -port 49983`（健康检查 `/health` 返回 204） |
| TCR | 实例 `tcr-mvlaq1sq`，域名 `euson-tcr.tencentcloudcr.com` |
