如何指定 AGS 实例使用 AgentCBS 系统盘
适用范围：仅支持 custom 自定义沙箱。 不适用于内置 code-interpreter、browser 等沙箱类型。
创建 custom 实例时，在请求的 metadata 中设置 x-ags-agent-cbs-system-disk 为字符串 "true"，即可声明本次实例使用 AgentCBS 系统盘。
这个参数在创建实例时生效。已有实例不能通过更新 metadata 把普通系统盘切换成 AgentCBS 系统盘；需要按下述方式新建实例。
1. 参数怎么传
|接入方式|参数位置|格式|
|-|-|-|
|E2B SDK / E2B HTTP API|创建请求的 metadata|字符串键值对象|
|AGS Cloud API StartSandboxInstance|请求体的 Metadata|Name、Value 对象数组|

统一使用字符串 "true"，不要写成 JSON 布尔值 true。将该键合并进已有 metadata，保留业务原有字段。
E2B Python SDK
在已有的 Sandbox.create() 调用中增加 metadata：
import os
from e2b import Sandbox

sandbox = Sandbox.create(
    template=os.environ["AGS_TOOL_ID"],
    api_key=os.environ["E2B_API_KEY"],
    domain=os.environ["AGS_E2B_DOMAIN"],
    validate_api_key=False,
    timeout=600,
    metadata={
        "x-ags-agent-cbs-system-disk": "true",
    },
)

print(sandbox.sandbox_id)
沿用已有 AGS E2B SDK 环境与认证配置。AGS_TOOL_ID 为目标 custom Tool ID，AGS_E2B_DOMAIN 为对应地域的 E2B domain，例如 ap-beijing.tencentags.com，不带 https:// 或 api. 前缀。
E2B HTTP API
向现有 E2B 服务的 POST /sandboxes 发送以下请求体，并沿用已有 X-API-KEY 认证：
{
  "templateID": "<你的 custom Tool ID>",
  "timeout": 600,
  "metadata": {
    "x-ags-agent-cbs-system-disk": "true"
  }
}
E2B 创建入口也支持同名 HTTP header：
x-ags-agent-cbs-system-disk: true
建议统一放在 body metadata。若 body 和 header 同时设置同一个键，非空 header 覆盖 body 的值，排障时应同时检查两处。这个 header 转换行为属于 E2B 入口，Cloud API 仍应使用 Metadata 请求字段。
AGS Cloud API
调用 StartSandboxInstance，在原有请求中加入 Metadata：
{
  "ToolId": "<你的 custom Tool ID>",
  "Timeout": "600s",
  "Metadata": [
    {
      "Name": "x-ags-agent-cbs-system-disk",
      "Value": "true"
    }
  ]
}
这是一段请求体示例，调用时沿用已有腾讯云 API 的地域、Endpoint 和签名配置。注意 Cloud API 的 Timeout 是时长字符串，E2B 的 timeout 是秒数。
2. 使用条件与限制
- 沙箱工具（Tool）类型为 custom，状态为 ACTIVE。
- 使用 E2B SDK 执行命令时，自定义镜像需已具备对应的 E2B 兼容执行环境。
- 系统盘由平台创建和管理，无需提前调用 CreateVolume，也无需指定盘 ID。数据盘的创建和挂载需单独配置。
- 本文介绍创建实例时选择系统盘类型。Snapshot、Fork、Pause/Resume 的使用条件请分别确认。
3. 创建后检查
确认实例创建完成、状态为 RUNNING，再执行简单的读写检查：
result = sandbox.commands.run(
    "echo agentcbs-write-ok > /tmp/agentcbs-check.txt; "
    "cat /tmp/agentcbs-check.txt; df -h /"
)
print(result.stdout)
assert result.exit_code == 0
预期输出包含 agentcbs-write-ok，并显示根目录磁盘使用情况。此检查用于确认实例可用和文件可读写；df 显示的文件系统名称不能单独用于判定存储后端。
创建参数中的 x-ags-agent-cbs-system-disk 可能不会在返回的 metadata 中保留，不能据此判断未启用。如需进一步核对，请向技术支持提供地域、实例 ID、Tool ID 和请求 ID。
仅用于测试的实例，在验证结束后可通过 sandbox.kill() 停止。
4. 常见问题
|问题|说明|
|-|-|
|内置 code-interpreter 或 browser 沙箱能否使用？|仅支持 custom 自定义沙箱。|
|已有实例能否切换系统盘类型？|不支持通过更新 metadata 切换；需携带该参数新建实例。|
|是否需要指定系统盘 ID？|不需要，平台自动管理系统盘。|
|返回 metadata 中没有该键是否代表失败？|不代表失败。该参数用于创建时指定系统盘类型，可能不会保留在返回的 metadata 中。|
|创建失败如何排查？|检查 Tool 类型与状态、参数位置、键名及字符串值；使用 E2B 时，同时检查同名 header 是否覆盖 body。仍有问题时提供请求 ID 联系技术支持。|
|修改系统盘容量是否会切换存储后端？|不会。容量与存储后端是不同配置，仍需在创建请求中指定本文开关。|
