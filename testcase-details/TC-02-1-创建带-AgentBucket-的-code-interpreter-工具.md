# TC-02-1 创建带 AgentBucket 的 code-interpreter 工具

| 项 | 值 |
|---|---|
| 结论 | **PASS** |
| 执行时间 | 2026-09-19 15:40:54 |
| 耗时 | 30.0s |
| 网络模式 | VPC |

## 测试目的

验证按 E2B subPath=spaceID 模式创建工具：只传 LibraryId、不传 SpaceId，工具应变为 ACTIVE 且回查 LibraryId 一致。

## 前置条件

SMH LibraryId=smh3qv6cmcoscm4i；spaceID=space3ly9r9ni7fhju；RoleArn 具备 QcloudSMHFullAccess；VPC=vpc-ovochv3a

## 测试步骤与结果

| # | 步骤 | 结论 | 耗时 | 说明 |
|---|------|------|------|------|
| 1 | CreateSandboxTool (code-interpreter) | ✅ PASS | 0.0s | ToolId=sdt-9nnj4qug |
| 2 | 等待工具 ACTIVE | ✅ PASS | 0.0s | Status=ACTIVE |
| 3 | 回查 LibraryId 与请求一致 | ✅ PASS | 0.0s | LibraryId=smh3qv6cmcoscm4i |
| 4 | 创建工具阶段未回填 SpaceId | ✅ PASS | 0.0s | 确认未传 SpaceId |

### 证据 1: CreateSandboxTool (code-interpreter)

```
{
  "ToolId": "sdt-9nnj4qug",
  "RequestId": "e4562a08-9831-4712-a618-5e7190dc76d5"
}
```

### 证据 3: 回查 LibraryId 与请求一致

```
[
  {
    "Name": "agentbucket",
    "StorageSource": {
      "AgentBucket": {
        "LibraryId": "smh3qv6cmcoscm4i",
        "AccessDomain": "smh3qv6cmcoscm4i.ap-beijing.api.tencentsmh.cn"
      }
    },
    "MountPath": "/mnt/data/agentbucket"
  }
]
```

## 附件

- `/root/ags/reports/artifacts/TC-02-1-tool-request.json` — tool-request
