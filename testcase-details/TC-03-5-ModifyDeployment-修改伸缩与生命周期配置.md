# TC-03-5 ModifyDeployment 修改伸缩与生命周期配置

| 项 | 值 |
|---|---|
| 结论 | **PASS** |
| 执行时间 | 2026-09-19 15:00:22 |
| 耗时 | 81.0s |

## 测试目的

验证修改配置后回读一致。注意：伸缩/生命周期/亲和对象是「完整替换」语义，必须提供该对象的全部字段。

## 前置条件

Deployment dpl-mkbphi9p 为 ACTIVE

## 测试步骤与结果

| # | 步骤 | 结论 | 耗时 | 说明 |
|---|------|------|------|------|
| 1 | ModifyDeployment 调用成功 | ✅ PASS | 0.0s |  |
| 2 | 伸缩配置已更新 | ✅ PASS | 0.0s | Scaling={'MinInstanceCount': 1, 'MaxInstanceCount': 5, 'MaxInstanceRequestConcurrency': 20} |
| 3 | 生命周期配置已更新 | ✅ PASS | 0.0s | IdleAction=PAUSE |

### 证据 1: ModifyDeployment 调用成功

```
{
  "Deployment": {
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
  },
  "RequestId": "0dcda136-0af3-4f8d-a3dc-50f1035e0daa"
}
```
