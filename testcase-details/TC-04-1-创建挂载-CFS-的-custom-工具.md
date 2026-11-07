# TC-04-1 创建挂载 CFS 的 custom 工具

| 项 | 值 |
|---|---|
| 结论 | **PASS** |
| 执行时间 | 2026-09-19 15:38:09 |
| 耗时 | 102.8s |
| 网络模式 | VPC |
| 被测镜像 | `euson-tcr.tencentcloudcr.com/sandbox/sandbox:v1` |

## 测试目的

验证 StorageSource.Cfs（FileSystemId=cfs-45a313f3e, Path=/）能被 AGS 接受，工具变为 ACTIVE 且回查配置一致。

## 前置条件

CFS cfs-45a313f3e 在 ap-beijing 可用（挂载点已建）；RoleArn 具备 CFS 权限

## 测试步骤与结果

| # | 步骤 | 结论 | 耗时 | 说明 |
|---|------|------|------|------|
| 1 | CreateSandboxTool | ✅ PASS | 0.0s | ToolId=sdt-8gyq17bg |
| 2 | 等待工具 ACTIVE | ✅ PASS | 0.0s | Status=ACTIVE |
| 3 | 回查 FileSystemId 一致 | ✅ PASS | 0.0s | FileSystemId=cfs-45a313f3e |
| 4 | 回查 Path 一致 | ✅ PASS | 0.0s | Path=/ |

### 证据 1: CreateSandboxTool

```
{
  "ToolId": "sdt-8gyq17bg",
  "RequestId": "dc92c15b-1df4-4358-8ca7-9c66ea39799a"
}
```

### 证据 3: 回查 FileSystemId 一致

```
[
  {
    "Name": "cfs-workspace",
    "StorageSource": {
      "Cfs": {
        "FileSystemId": "cfs-45a313f3e",
        "Path": "/"
      }
    },
    "MountPath": "/mnt/cfs"
  }
]
```

## 附件

- `/root/ags/reports/artifacts/TC-04-1-tool-request.json` — tool-request
