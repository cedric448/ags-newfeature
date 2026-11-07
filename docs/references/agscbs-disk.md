AgentCBS 数据盘接入
AgentCBS 数据盘通过独立的 Volume 管理。先创建数据卷，再在创建 custom 沙箱实例时指定挂载目录。实例停止后保留 Volume，后续实例可以继续挂载同一 Volume 使用已有数据。
本文介绍显式创建、挂载 Volume 的方式。沙箱类型使用 custom，并在创建实例时开启 AgentCBS 系统盘。 系统盘开关与数据盘挂载配置需要同时传入。
1. 使用条件与限制
- 数据卷和沙箱实例位于同一账号、同一地域。本文请求均以广州 ap-guangzhou 为例。
- custom Tool 已处于 ACTIVE 状态，数据卷也需处于 ACTIVE 后才能挂载。
- 数据卷使用 ReadWriteOnce：同一时刻只能被一个实例占用。实例暂停时仍可能占用数据卷，切换实例前应先停止原实例。
- 一个实例最多挂载一块 AgentCBS 数据盘；不支持共享读写、只读挂载、SubPath 或挂载到根目录 /。
- 挂载在创建实例时指定，暂不支持通过公开 API 为运行中的实例动态添加、卸载或更换数据盘。
- 数据盘使用 ext4 文件系统，无需自行格式化。不要在需要保留数据的卷上执行格式化操作。
2. 创建数据卷
首次使用容量规格时的注意事项
在某个地域首次使用尚未初始化的数据盘容量规格时，平台需要先完成该规格的初始化，首次创建耗时可能较长需要数秒，并可能因等待初始化而超时或返回错误。已启动的初始化任务仍可能在后台继续执行，可稍后使用相同请求参数和 ClientToken 重试；若持续失败，请保留请求 ID 联系技术支持。
规格初始化完成后，同一地域后续创建相同规格的数据盘会复用已有初始化结果，无需重复初始化。各数据卷的数据相互独立。
调用 Cloud API CreateVolume，地域选择 ap-guangzhou，请求体如下。认证、Endpoint 和签名沿用现有腾讯云 API 配置。
{
  "VolumeName": "agent-data-demo",
  "StorageType": "AgentCbs",
  "Storage": {
    "AgentCbs": {
      "Capacity": "20Gi"
    }
  },
  "AccessMode": "ReadWriteOnce",
  "ClientToken": "agent-data-demo-create-001"
}
|字段|说明|
|-|-|
|VolumeName|数据卷名称，请替换为自己的名称。|
|StorageType|固定为 AgentCbs，注意大小写。|
|Storage.AgentCbs.Capacity|容量字符串，使用正整数加 Gi，例如 20Gi。可用容量以服务支持范围为准。|
|AccessMode|固定为 ReadWriteOnce。|
|ClientToken|幂等标识。同一次创建的重试沿用该值，创建不同卷时使用新值。|

保存响应中的 Volume.VolumeId，后续挂载和删除均使用这个 ID。AgentCBS 数据卷不需要传 StorageRoleArn，也不需要自行指定底层磁盘 ID、可用区、盘型或格式化参数。
调用 DescribeVolumeList 查询状态：
{
  "VolumeIds": ["<你的 VolumeId>"],
  "Limit": 1
}
从 VolumeSet 中确认目标卷的 Status 为 ACTIVE。若仍为 CREATING，等待后再查询；若为 FAILED，联系技术支持核查，不要继续挂载。
3. 挂载到沙箱实例
调用 StartSandboxInstance，在请求中同时提供 StorageMounts 和系统盘开关：
{
  "ToolId": "<你的 custom Tool ID>",
  "Timeout": "600s",
  "StorageMounts": [
    {
      "Name": "agent-data",
      "Volume": {
        "VolumeId": "<你的 VolumeId>"
      },
      "MountPath": "/workspace/data"
    }
  ],
  "Metadata": [
    {
      "Name": "x-ags-agent-cbs-system-disk",
      "Value": "true"
    }
  ]
}
Name 是该实例内的挂载名称，MountPath 是容器内的绝对路径。挂载后该目录展示数据卷的内容；镜像中原本位于同一路径的文件会被挂载遮盖，建议使用专门的数据目录。
使用 E2B Python SDK 挂载
先通过 Cloud API 创建 Volume，再在 E2B 创建请求的 metadata 中提供 x-storage。它的值是 JSON 字符串，内部字段使用小驼峰命名：
import json
import os
from e2b import Sandbox

sandbox = Sandbox.create(
    template=os.environ["AGS_TOOL_ID"],
    api_key=os.environ["E2B_API_KEY"],
    domain="ap-guangzhou.tencentags.com",
    validate_api_key=False,
    timeout=600,
    metadata={
        "x-ags-agent-cbs-system-disk": "true",
        "x-storage": json.dumps([
            {
                "name": "agent-data",
                "volume": {"volumeId": os.environ["AGS_VOLUME_ID"]},
                "mountPath": "/workspace/data",
            }
        ]),
    },
)
AGS_TOOL_ID 必须指向 custom Tool，镜像需具备 E2B 兼容执行环境。AGS_VOLUME_ID 是已创建并处于 ACTIVE 的数据卷 ID。
4. 验证读写与数据保留
在实例 A 内执行以下命令。示例文件名应替换为本次测试的唯一名称，避免覆盖已有文件：
findmnt -T /workspace/data
df -h /workspace/data
printf 'agentcbs-data-check\n' > /workspace/data/agentcbs-check-demo.txt
sync
cat /workspace/data/agentcbs-check-demo.txt
sha256sum /workspace/data/agentcbs-check-demo.txt
确认挂载目录可访问，文件读回内容为 agentcbs-data-check，并记录校验值。
随后验证跨实例保留：
1. 停止实例 A，保留 Volume，不调用 DeleteVolume。
2. 等待实例停止、数据卷解除占用。如 DescribeVolumeList 返回 MountedInstanceId，确认它不再指向实例 A。
3. 使用第 3 节请求创建实例 B，继续引用同一个 VolumeId。
4. 在实例 B 中读取相同文件并计算校验值，确认与实例 A 一致。
若新实例创建返回 ResourceInUse，先确认原实例已停止并等待占用释放，不要尝试同时挂载。
5. 释放资源
停止实例只结束实例运行，不会删除独立创建的 Volume 及其中数据。需要继续使用数据时，保留 Volume 即可。
确定不再需要数据时，先停止占用该卷的实例，再调用 DeleteVolume：
{
  "VolumeId": "<你的 VolumeId>"
}
显式删除 Volume 会清理其数据，删除前请确认不再需要。删除后可通过 DescribeVolumeList 确认该卷不再返回；底层资源清理由服务异步完成。
6. 常见问题
|现象|处理方式|
|-|-|
|LimitExceeded.Volume|账号在目标地域的数据卷数量已达上限。删除明确不再需要的卷，或申请提高配额。不要为绕过配额删除仍需保留的数据。|
|ResourceInUse|数据卷仍被实例占用。停止原实例、等待释放后，再挂载或删除。|
|InvalidParameter|检查 AgentCbs 大小写、Capacity 的 nGi 格式、ReadWriteOnce 和挂载路径。|
|已创建数据卷但实例看不到目录|确认创建实例时传了具体 VolumeId、MountPath，同时携带系统盘开关。|
|停止实例后仍能查到 Volume|属于预期行为；数据卷需要单独删除。|
|需要快照、Fork 或暂停恢复|本文验证流程是停止后重新挂载；其他生命周期能力及限制需另行确认。|
