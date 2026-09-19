# TC-02-8 负例：不存在的 spaceID 挂载行为

| 项 | 值 |
|---|---|
| 结论 | **PASS** |
| 执行时间 | 2026-09-19 14:43:01 |
| 耗时 | 0.8s |
| 网络模式 | VPC |

## 测试目的

文档说明：传入不存在的 spaceID 时实例仍可启动，但挂载目录不会被创建/访问报 no such file or directory。

## 前置条件

同 TC-02-3

## 测试步骤与结果

| # | 步骤 | 结论 | 耗时 | 说明 |
|---|------|------|------|------|
| 1 | 实例仍能启动 | ✅ PASS | 0.0s | sandbox_id=ou7cjb6zexev3n2tyyvkqzk6vn6p7awl7sosiviq |
| 2 | 记录挂载目录访问结果 | ✅ PASS | 0.0s | exit=0 |

### 证据 2: 记录挂载目录访问结果

```
{
  "stdout": "ls: cannot open directory '/mnt/data/agentbucket-alt': No such file or directory\n",
  "stderr": ""
}
```

## 备注

- 按文档预期应报 no such file or directory；此处仅记录实际行为，不作强断言
