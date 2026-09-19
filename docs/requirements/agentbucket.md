腾讯云Agent沙箱支持AgentBucket
AgentBucket 是 AGS（Agent Sandbox 服务）基于 SMH（智能媒资托管）提供的沙箱持久化存储能力。本 Cookbook 通过一个完整的「创建工具 → 启动沙箱 → 挂载 AgentBucket → 读写文件 → 验证持久化」示例，展示如何在业务沙箱中使用 AgentBucket。
功能特性
   持久化存储：沙箱实例销毁后，写入 AgentBucket 的文件仍然保留。
   目录挂载：将 AgentBucket/SMH 空间挂载为沙箱内普通目录，例如 /mnt/data/agentbucket。
   E2B subPath 指定空间：启动 E2B 实例时通过 metadata.x-mounts[].subPath 传入目标 spaceID。
   一对多挂载：同一个存储源可通过不同实例级挂载配置映射到多个路径。
   只读保护：支持工具级和实例级 ReadOnly，适合数据集、模型等只读资源。
   Custom 沙箱适配：可与自定义镜像配合使用，通过文件 API 或 shell 命令访问挂载目录。
   Code-Interpreter 同样适用：AgentBucket 对 code-interpreter 类型工具同样生效，且不需要 CustomConfiguration（镜像、envd、端口、Probe），创建 payload 更简洁。
业务场景
适用于需要在沙箱生命周期之外保存数据的场景：
   AI Agent 任务的输入、输出、日志和中间文件持久化。
   多次启动沙箱实例复用同一份工作目录。
   按用户、任务、租户隔离工作空间。
   只读挂载数据集、模型文件、模板文件。
   启动实例时通过 E2B metadata.x-mounts 把 AgentBucket 挂载到 /mnt/data/agentbucket 等路径。
核心概念
StorageMount
StorageMount 是工具级存储声明，在创建 SandboxTool 时配置。本文主流程采用 LibraryId 创建工具、启动实例时通过 E2B metadata.x-mounts[].subPath 传入目标 spaceID。

 
字段说明：
字段    说明
Name    挂载名称，后续 E2B metadata.x-mounts[].name 必须与它一致。
MountPath   工具级默认挂载路径，必须是合法绝对路径；启动实例时可被 metadata.x-mounts[].mountPath 覆盖。
ReadOnly    是否只读。工具级只读不能被实例级放宽。
LibraryId   SMH 媒体库 ID，创建工具时必填，格式为 smh 后接 13 位小写字母或数字。
SpaceId 本文 E2B subPath = spaceID 模式下创建工具时不要传；spaceID 只在启动实例阶段通过 metadata.x-mounts[].subPath 传入。
AccessDomain 是历史兼容字段，不出现在本文 API 调用示例中。用户侧创建工具时只需要传 LibraryId。
SpaceId 与 E2B subPath
本文采用的 E2B 模式规则：
1.  创建沙箱工具时，只在 StorageSource.AgentBucket 中传 LibraryId，不要传 SpaceId，也不要写 "SpaceId": ""。
2.  启动 E2B 沙箱实例时，通过 metadata.x-mounts[].subPath 传目标 spaceID。
3.  metadata.x-mounts[].mountPath 可覆盖工具级 MountPath，例如从 /mnt/cos 覆盖到 /mnt/data/agentbucket。
4.  如果创建工具时也传了 SpaceId，启动实例时又把 spaceID 放进 subPath，最终会同时存在 space_id 和 sub_path，与本文模式不一致。
MountOptions / E2B x-mounts
E2B metadata.x-mounts 会被接入层转换为后端实例级 MountOptions。本文示例直接使用 E2B 小驼峰字段：

 
字段说明：
字段    说明
name    引用工具级 StorageMount.Name。
mountPath   可选，覆盖工具级默认挂载路径。
subPath 本文 AgentBucket E2B 模式下填写目标 spaceID；格式上仍是相对路径，不能以 / 开头，不能包含 .、.. 或连续 /。
readOnly    可选，实例级只读收紧。
前置准备
使用 AgentBucket 前，需要完成三类配置：AGS OpenAPI 调用配置、Role 配置、SMH 资源配置。
1. AGS OpenAPI / SDK 调用配置
本 Cookbook 的主路径使用腾讯云 Python SDK 调用 AGS OpenAPI，不要求用户手动到控制台填写自定义沙箱工具。
 其中"创建工具"阶段通过 Python SDK 的通用 call_json 能力直接提交原始请求体；"启动实例"阶段可使用 E2B SDK 或腾讯云 Python SDK typed request，本 Cookbook 主流程以 E2B SDK 演示。
准备可调用 AGS OpenAPI 的账号和 endpoint，用于执行：
   CreateSandboxTool
   DescribeSandboxToolList / 查询工具状态
   StartSandboxInstance
   StopSandboxInstance
   沙箱文件 API 或命令执行 API
以 Python SDK 为例，先准备运行环境：

 
说明：当前最新版 tencentcloud-sdk-python 还没有 AgentBucketStorageSource typed model。
 因此本 Cookbook 的"创建工具"步骤使用 Python SDK 的 AgsClient.call_json 直接提交原始 dict；"启动实例"步骤仍可继续使用腾讯云 Python SDK。
⚠️ call_json 是 tencentcloud-sdk-python 的通用调用入口，并非 CreateSandboxTool 的官方公开 API。等 SDK 发布支持 AgentBucket 的 typed model（AgentBucketStorageSource）后，建议优先迁移到 typed 调用以获得 IDE 提示和字段校验；如果未来该方法发生不兼容变更，也可参考腾讯云 OpenAPI v3 签名文档自行构造 HTTP 请求作为兜底。
当前已验证可用的 E2B Python SDK 组合：
   e2b_code_interpreter==2.2.1
   e2b==2.23.1
说明：AGS 目前签发 ark_... 格式的 API Key，部分环境可能使用 e2b_... 格式。上述 SDK 版本组合（e2b_code_interpreter==2.2.1 + e2b==2.23.1）经验证对两种格式的 API Key 均兼容。如果升级到更新的 E2B SDK 版本，新版可能只校验 e2b_... 格式，届时 ark_... 格式的 Key 可能会被拒绝。
配置调用凭据和地域：

 
上述密钥只用于本地调用腾讯云 OpenAPI，请不要写入代码仓库。
2. Role 配置
创建工具时必须配置 RoleArn，用于沙箱服务在挂载 AgentBucket 时换取临时凭证。
RoleArn 格式：

 
配置要求：
1.  角色存在：在对应账号下创建 CAM Role，记录完整 RoleArn。
2.  允许服务代入：角色信任关系需要允许 AGS 沙箱服务链路代入该角色，具体主体可参考腾讯云 AGS 接入文档。
3.  授权访问 SMH：角色需要具备访问目标 SMH library/space 的权限，否则工具可以创建成功但实例启动或挂载可能失败。
4.  请求中传完整 ARN：CreateSandboxTool.RoleArn 传完整 qcs::cam::uin/...:roleName/...，不要只传 role name。
建议直接给该 Role 关联以下 CAM 预设策略：
   QcloudSMHFullAccess：智能媒资托管（SMH）全读写访问权限。只要使用 AgentBucket，就应关联这个策略。
   QcloudCCRFullAccess：容器服务-镜像仓库（CCR）全读写访问权限。如果您使用的自定义镜像来自 CCR（ccr.ccs.tencentyun.com/...），则需要这个策略。
   QcloudTCRFullAccess：容器镜像服务（TCR）全读写权限。只有当您的自定义镜像来自 TCR 时才需要。
本 Cookbook 不预置任何镜像，请按您自己的镜像来源关联对应策略：CCR 镜像关联 QcloudCCRFullAccess，TCR 镜像关联 QcloudTCRFullAccess。
Role 配置检查清单：
检查项  说明
Role 是否存在   能在 CAM 控制台或权限系统中查到该角色。
RoleArn 是否完整    必须包含账号 UIN 和 roleName。
信任关系是否正确    沙箱服务链路可以 AssumeRole。
SMH 权限是否覆盖目标资源    至少关联 QcloudSMHFullAccess，并能访问目标 LibraryId / spaceID 对应资源。
镜像仓库权限是否正确    CCR 镜像至少关联 QcloudCCRFullAccess；TCR 镜像改为关联 QcloudTCRFullAccess。
是否与请求账号匹配  角色账号、SMH 资源归属、调用账号需要符合业务授权关系。
3. SMH 申请与配置
AgentBucket 依赖 SMH 资源。接入前需要先申请或创建 SMH library，并记录两类信息：

 
用途：
   LibraryId：创建沙箱工具时传入 StorageSource.AgentBucket.LibraryId。
   spaceID：启动 E2B 沙箱实例时传入 metadata.x-mounts[].subPath。
   AccessDomain：历史兼容字段，本文 API 示例不要求用户准备或传入。
3.1 创建工具阶段
创建工具阶段只声明使用哪个 SMH library，不声明具体 spaceID：

 
注意：在本文 E2B subPath = spaceID 模式下，创建工具时不要传 SpaceId，也不要写 "SpaceId": ""。
3.2 启动实例阶段
启动实例阶段通过 E2B metadata.x-mounts[].subPath 指定目标 spaceID：

 
同一个工具可以在不同实例中传不同 subPath，从而挂载不同 spaceID 对应的数据空间。
3.3 SMH 信息确认
信息    是否需要用户准备    用途
LibraryId   必填    创建 AgentBucket 工具级挂载。
spaceID 必填    启动 E2B 实例时作为 metadata.x-mounts[].subPath 传入。
AccessDomain    不需要  历史兼容 / 内部解析信息，本文 API 示例不传。
LibrarySecret / SDK Token   可选    仅用于通过 SMH SDK 预置目录或文件，不需要传给 AGS。
4. Custom 镜像配置
如果使用 Custom 沙箱，建议镜像中启动 envd，方便通过文件 API 操作挂载目录：

 
说明：
   -l 让 bash 走 login shell 加载 /etc/profile、~/.bash_profile 中的 PATH，确保 envd 等二进制被找到。
   > /tmp/envd.log 2>&1 把 envd 的输出落盘，方便挂载或启动失败时排查。
   AGS Custom Tool 当前后端要求 Probe 必填，未设置会返回 MissingParameter: CustomConfiguration.Probe is required。本节示例与执行流程章节使用的 payload 完全一致，避免拷贝时出现差异。
Code-Interpreter 工具不需要 CustomConfiguration：如果使用 ToolType: "code-interpreter"，只需要 ToolName、ToolType、RoleArn、NetworkConfiguration、StorageMounts，无需 CustomConfiguration（镜像、Command、Args、Ports、Probe 等字段均不需要）。AgentBucket 挂载对 code-interpreter 和 custom 两种类型完全一致。
5. 挂载路径约束
推荐挂载路径：

 
避免挂载到系统路径，否则容器内基础工具链可能损坏：

 
执行流程
1. 配置示例所需环境变量

 
上面所有以 <...> 形式出现的占位符都需要替换为您自己账号下的真实资源；本 Cookbook 不附带任何可直接复制使用的真实凭据或资源标识。
2. 通过腾讯云 Python SDK 创建带 AgentBucket 的工具
当前可执行主路径是腾讯云 Python SDK 的通用 call_json。因为最新版 Python SDK 还未发布 AgentBucketStorageSource typed model，所以这里直接构造 StorageSource.AgentBucket 原始 dict 并提交给云 API。
创建 create_agentbucket_tool.py：

 
运行：

 
预期结果：
   CreateSandboxTool 调用成功。
   工具状态最终变为 ACTIVE。
   回查工具时，Response.SandboxToolSet[0].StorageMounts[].StorageSource.AgentBucket.LibraryId 与请求一致。
   本模式下创建工具阶段不传 SpaceId，spaceID 会在启动实例阶段通过 E2B metadata.x-mounts[].subPath 传入。
   CustomConfiguration.Probe 必须显式传入，否则云 API 会返回 MissingParameter: CustomConfiguration.Probe is required。
3. 通过 E2B 协议启动沙箱实例
关键点：
   Sandbox.create(template=...) 里的 template 传的是工具名称 ToolName，不是 sdt-... 形式的 ToolId。
   本文通过 metadata["x-mounts"] 覆盖实例级挂载配置，其中 subPath 填目标 spaceID。
   metadata.x-mounts[].mountPath 会覆盖创建工具时的工具级 MountPath；下面示例把 /mnt/cos 覆盖为 /mnt/data/agentbucket。
创建 e2b_agentbucket_smoke.py：

 
运行：

 
预期结果：
   Sandbox.create(template=TOOL_NAME, ...) 调用成功。
   返回的 sandbox_id 非空。
   sandbox.commands.run(...) 可以在 /mnt/data/agentbucket 下写入并读回文件。
4. 在沙箱内通过 E2B 文件 API 读写挂载目录
commands.run 适合执行任意 shell 流程，但对 Agent 来说更"原生"的方式是直接用 sandbox.files 读写文件，不需要拼接 shell 字符串、不需要处理引号转义，也更容易把"读取/写入"作为工具暴露给上层 LLM 调用。
下面例子在同一个 /mnt/data/agentbucket 目录下，展示 files.write / files.read / files.list / files.exists 的典型用法：

 
预期输出：

 
如需要执行 shell 任务（例如批量解压、运行脚本），仍可继续使用 sandbox.commands.run(...)，两种方式可以在同一个沙箱实例中混用。
5. 验证持久化
第一次启动沙箱时通过 files.write 写入一个文件，杀掉沙箱后再启动一个全新的沙箱实例（同一个 ToolName、同一个 x-mounts[].subPath），看能否读到：

 
预期：
   两次的 sandbox_id 不同（说明确实是新实例，不是 reconnect）。
   第二个实例能读到 persisted-by-agentbucket，说明数据由 AgentBucket 持久化、不依赖单个沙箱实例的生命周期。
注意：跨实例可见的前提是两次启动使用相同的 StorageMount.Name 与相同的 metadata.x-mounts[].subPath。如果第二次启动改了 subPath，会挂载到不同数据空间，看不到旧文件是预期行为。
使用示例
AgentBucket 的使用分两层：
   工具级 StorageMounts：在 CreateSandboxTool 时声明工具默认挂载哪个 SMH library（声明"有什么"）。本文主路径只传 LibraryId，不传 AccessDomain，不传 SpaceId。
   实例级 E2B metadata.x-mounts：在 Sandbox.create(...) 时覆盖 mountPath / readOnly / subPath（声明"这次怎么用"）。本文主路径中 subPath 填目标 spaceID。
下面示例都假设已经按"前置准备"配好 TENCENTCLOUD_*、ROLE_ARN、AGENTBUCKET_LIBRARY_ID、AGENTBUCKET_SPACE_ID 等环境变量。
示例一：基础挂载到指定 spaceID
工具级声明：

 
E2B 启动实例时指定 spaceID 和最终挂载路径：

 
沙箱内：

 
示例二：同一工具挂载不同 spaceID
同一个工具可以复用同一个 StorageMount.Name，不同实例启动时传不同 subPath：

 
示例三：只读挂载
如果工具级已经配置 ReadOnly=True，实例级不能放宽为可写；如果工具级是可写，实例级可以通过 readOnly=True 收紧：

 
预期结果：
   files.list 能列出挂载目录文件。
   files.write 写入失败或被拒绝，说明实例级只读收紧生效。
预期输出
完成基础流程后，应能观察到：

 
本文 E2B 模式下，目录映射类似：

 
常见问题
创建工具提示缺少 RoleArn
检查 CreateSandboxTool 请求中是否填写了：

 
只要配置了 StorageMounts，RoleArn 就是必填项。
已配置 RoleArn 但实例启动或挂载失败
优先检查 Role 配置：
1.  RoleArn 是否是完整 ARN，而不是 role name。
2.  角色信任关系是否允许沙箱服务链路代入。
3.  角色权限是否覆盖目标 SMH library/space。
4.  RoleArn 所属账号与 SMH 资源归属是否符合授权关系。
5.  如果同一工具还挂载 COS 等其他存储，角色权限是否同时覆盖这些资源。
为什么 API 示例里不传 AccessDomain
AccessDomain 是历史兼容字段。本文 API 示例使用 LibraryId 创建工具，不要求用户传 AccessDomain。AGS 后端会根据 LibraryId 解析挂载所需信息。
如果遇到 LibraryId 相关错误，优先检查：
   LibraryId 是否形如 smh2ke12fou96sys，即 smh 后接 13 位小写字母或数字。
   LibraryId 是否属于当前地域。
   当前账号和 RoleArn 是否有访问该 SMH library 的权限。
沙箱内看不到挂载目录
优先检查：
1.  实例是否启动成功并处于 RUNNING。
2.  启动实例时 metadata.x-mounts[].name 是否与工具级 StorageMount.Name 一致。
3.  启动实例时 metadata.x-mounts[].mountPath 是否是您检查的路径，例如 /mnt/data/agentbucket。
4.  metadata.x-mounts[].subPath 是否填写了目标 spaceID，且两次启动是否一致。
5.  RoleArn 是否有访问目标 SMH/AgentBucket 的权限。
6.  当前地域是否同时开通 AgentBucket 服务和 AGS。
7.  metadata.x-mounts[].subPath 对应的 spaceID 是否真实存在。如果传入了一个不存在的 spaceID，沙箱实例虽然可以正常启动，但挂载目录不会被创建，访问时会报 no such file or directory。
写文件失败
优先检查：
1.  工具级 ReadOnly 是否为 true。
2.  实例级 metadata.x-mounts[].readOnly 是否为 true。
3.  写入路径是否位于挂载目录内。
4.  目标目录是否存在。
实例销毁后重新启动读不到文件
确认两次启动使用的是同一个实际目录：
   StorageMount.Name 一致，即 metadata.x-mounts[].name 一致。
   metadata.x-mounts[].subPath 一致，即传入同一个 spaceID。
   mountPath 是容器内路径，变化不影响持久化位置；但如果路径变化，需要到新的容器路径下读取文件。
创建工具时 SpaceId 要不要填
本文 E2B subPath = spaceID 模式下，创建工具时不要传 StorageSource.AgentBucket.SpaceId。
正确做法：

 
不要写：

 
也不要在本文模式下写：

 
目标 spaceID 应在启动实例时通过 metadata.x-mounts[].subPath 传入。
metadata.x-mounts[].subPath 应该怎么填
在本文 AgentBucket E2B 模式下，subPath 填目标 spaceID：

 
格式上 subPath 仍按实例级挂载子路径校验：不能以 / 开头，不能包含 .、.. 或连续 /。
技术亮点
1. E2B subPath 指定 spaceID
创建工具时只声明 LibraryId；启动实例时通过 metadata.x-mounts[].subPath 指定目标 spaceID。同一个工具可以复用到不同实例，不同实例通过不同 spaceID 访问不同数据空间。

 
2. 工具级声明 + 实例级覆盖
工具定义默认存储能力，实例按需选择路径、spaceID 和只读策略：

 
3. 权限收紧模型
实例级可以把可写挂载收紧为只读，但不能把工具级只读放宽为可写。

 



