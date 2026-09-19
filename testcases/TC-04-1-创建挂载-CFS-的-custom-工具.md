# TC-04-1 创建挂载 CFS 的 custom 工具

| 项 | 值 |
|---|---|
| 结论 | **PASS** |
| 执行时间 | 2026-09-19 15:07:49 |
| 耗时 | 110.8s |
| 网络模式 | VPC |

## 测试目的

验证 StorageSource.Cfs（FileSystemId=cfs-cunkkj23, Path=/）能被 AGS 接受，工具变为 ACTIVE 且回查配置一致。

## 前置条件

CFS cfs-cunkkj23 在 ap-beijing 可用；RoleArn 具备 CFS 权限

## 测试步骤与结果

| # | 步骤 | 结论 | 耗时 | 说明 |
|---|------|------|------|------|
| 1 | CreateSandboxTool | ✅ PASS | 0.0s | ToolId=sdt-rqtqp5qk |
| 2 | 等待工具 ACTIVE | ✅ PASS | 0.0s | Status=ACTIVE |
| 3 | 回查 FileSystemId 一致 | ✅ PASS | 0.0s | FileSystemId=cfs-cunkkj23 |
| 4 | 回查 Path 一致 | ✅ PASS | 0.0s | Path=/ |

### 证据 1: CreateSandboxTool

```
{
  "ToolId": "sdt-rqtqp5qk",
  "RequestId": "40ff94c3-c5f5-4bdc-a173-5aa5d4f913b9"
}
```

### 证据 3: 回查 FileSystemId 一致

```
[
  {
    "Name": "cfs-workspace",
    "StorageSource": {
      "Cfs": {
        "FileSystemId": "cfs-cunkkj23",
        "Path": "/"
      }
    },
    "MountPath": "/mnt/cfs"
  }
]
```

## 附件

- `/root/ags/reports/artifacts/TC-04-1-tool-request.json` — tool-request
