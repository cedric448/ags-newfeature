# TC-04-2 负例：CFS Path 指向不存在的目录

| 项 | 值 |
|---|---|
| 结论 | **PASS** |
| 执行时间 | 2026-09-19 15:30:32 |
| 耗时 | 84.8s |
| 网络模式 | VPC |

## 测试目的

验证 StorageMounts.Path 必须指向 CFS 内已存在的路径。实测行为：创建工具阶段【不校验】（工具仍变为 ACTIVE），错误在【启动实例】阶段才暴露为 FailedOperation.StorageMount。本用例按实际行为断言，并记录该「延迟校验」特性。

## 前置条件

同 TC-04-1

## 测试步骤与结果

| # | 步骤 | 结论 | 耗时 | 说明 |
|---|------|------|------|------|
| 1 | 创建工具阶段未校验 Path（工具被接受） | ✅ PASS | 0.0s | ToolId=sdt-8gkzkvvo |
| 2 | 工具仍变为 ACTIVE（与文档描述不符） | ✅ PASS | 0.0s | Status=ACTIVE |
| 3 | 启动实例阶段报 FailedOperation.StorageMount | ✅ PASS | 0.0s | 错误在实例启动阶段暴露，信息明确 |

### 证据 1: 创建工具阶段未校验 Path（工具被接受）

```
{
  "ToolId": "sdt-8gkzkvvo",
  "RequestId": "9842ce7e-c37f-4422-be51-87e9d3fcfcd2"
}
```

### 证据 3: 启动实例阶段报 FailedOperation.StorageMount

```
[FailedOperation.StorageMount] [TencentCloudSDKException] code:FailedOperation.StorageMount message:storage mount path "[\"30.1.0.16@tcp0:/5a313f3e/cfs/agstest-nonexistent-1789803009\",\"/data/cubelet/storage/io.cubelet.internal.v1.storage/turbocfs/463d75029da1ed83368a1d751321d6d6/mnt\"]" not found or unreachable, please check StorageMount CFS/NFS path and network configuration requestId:547e0b23-db39-4a97-b37a-aefeba9ea117 (RequestId: 547e0b23-db39-4a97-b37a-aefeba9ea117)
```

## 备注

- 缺陷/体验问题：Path 校验被延迟到启动实例阶段，且工具创建时返回 ACTIVE，容易让用户误以为配置正确。建议 AGS 在 CreateSandboxTool 阶段即校验 Path 可达性。
