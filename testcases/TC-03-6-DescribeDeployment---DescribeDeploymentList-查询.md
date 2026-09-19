# TC-03-6 DescribeDeployment / DescribeDeploymentList 查询

| 项 | 值 |
|---|---|
| 结论 | **PASS** |
| 执行时间 | 2026-09-19 15:00:25 |
| 耗时 | 77.7s |

## 测试目的

验证按 ID 单查与列表查询都能命中刚创建的 Deployment。

## 前置条件

Deployment dpl-mkbphi9p 存在

## 测试步骤与结果

| # | 步骤 | 结论 | 耗时 | 说明 |
|---|------|------|------|------|
| 1 | DescribeDeployment 命中 | ✅ PASS | 0.0s | Name=agstest-dpl-1789801210 |
| 2 | DescribeDeploymentList 命中 | ✅ PASS | 0.0s | 列表共 1 条 |

### 证据 1: DescribeDeployment 命中

```
{
  "DeploymentId": "dpl-mkbphi9p",
  "DeploymentName": "agstest-dpl-1789801210",
  "ToolId": "sdt-q3df21oo",
  "ScalingConfiguration": {
    "MinInstanceCount": 1,
    "MaxInstanceCount": 5,
    "MaxInstanceRequestConcurrency": 20
  },
  "LifecycleConfiguration": {
    "IdleTimeoutSeconds": 600,
    "IdleAction": "PAUSE"
  },
  "AffinityConfiguration": {
    "Mode": "BEST_EFFORT",
    "HeaderName": "X-Tencent-Agr-Affinity-Id"
  },
  "Status": "ACTIVE",
  "CreatedTime": "2026-09-19T07:00:17Z",
  "UpdatedTime": "2026-09-19T07:00:22Z",
  "Tags": []
}
```

### 证据 2: DescribeDeploymentList 命中

```
[
  "dpl-mkbphi9p"
]
```
