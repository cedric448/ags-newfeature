# TC-03-3 创建 Deployment 并等待 ACTIVE

| 项 | 值 |
|---|---|
| 结论 | **PASS** |
| 执行时间 | 2026-09-19 15:00:17 |
| 耗时 | 86.4s |

## 测试目的

绑定 Persistent 工具创建弹性部署，验证默认值物化（伸缩 / 生命周期 / 亲和）。

## 前置条件

工具 agstest-tc03-1789801210 已 ACTIVE 且 Persistent=true

## 测试步骤与结果

| # | 步骤 | 结论 | 耗时 | 说明 |
|---|------|------|------|------|
| 1 | CreateDeployment | ✅ PASS | 0.0s | DeploymentId=dpl-mkbphi9p |
| 2 | 状态为 ACTIVE | ✅ PASS | 0.0s | Status=ACTIVE |
| 3 | 伸缩配置已物化 | ✅ PASS | 0.0s | Scaling={'MinInstanceCount': 0, 'MaxInstanceCount': 3, 'MaxInstanceRequestConcurrency': 10} |
| 4 | 生命周期配置已物化 | ✅ PASS | 0.0s | IdleAction=STOP |
| 5 | 亲和配置含 HeaderName | ✅ PASS | 0.0s | HeaderName=X-Tencent-Agr-Affinity-Id |

### 证据 1: CreateDeployment

```
{
  "Deployment": {
    "DeploymentId": "dpl-mkbphi9p",
    "DeploymentName": "agstest-dpl-1789801210",
    "ToolId": "sdt-q3df21oo",
    "ScalingConfiguration": {
      "MinInstanceCount": 0,
      "MaxInstanceCount": 3,
      "MaxInstanceRequestConcurrency": 10
    },
    "LifecycleConfiguration": {
      "IdleTimeoutSeconds": 300,
      "IdleAction": "STOP"
    },
    "AffinityConfiguration": {
      "Mode": "BEST_EFFORT",
      "HeaderName": "X-Tencent-Agr-Affinity-Id"
    },
    "Status": "ACTIVE",
    "CreatedTime": "2026-09-19T07:00:17Z",
    "UpdatedTime": "2026-09-19T07:00:17Z",
    "Tags": []
  },
  "RequestId": "75a127c9-46f4-4493-81a6-8e6883cc19f0"
}
```

## 附件

- `/root/ags/reports/artifacts/TC-03-3-create-deployment-request.json` — create-deployment-request
