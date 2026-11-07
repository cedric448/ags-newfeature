# TC-02-6 同一工具不同 subPath 数据空间隔离

| 项 | 值 |
|---|---|
| 结论 | **PASS** |
| 执行时间 | 2026-09-19 15:41:21 |
| 耗时 | 2.6s |
| 网络模式 | VPC |
| 被测镜像 | `euson-tcr.tencentcloudcr.com/cedricbwang/test:v1` |

## 测试目的

同一工具、同一 StorageMount.Name，换一个 subPath 启动实例，应看不到 TC-02-5 写入的文件。

## 前置条件

TC-02-5 已在 spaceID A 写入数据

## 测试步骤与结果

| # | 步骤 | 结论 | 耗时 | 说明 |
|---|------|------|------|------|
| 1 | 不同 subPath 看不到原空间数据 | ✅ PASS | 0.0s | 隔离生效（space=space3ly9r9ni7fhju-alt） |

### 证据 1: 不同 subPath 看不到原空间数据

```
{
  "stdout": "ls: cannot access '/mnt/data/agentbucket-alt/agstest': No such file or directory\n=== exists check ===\nNOT-FOUND\n",
  "stderr": ""
}
```
