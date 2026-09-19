# TC-03-4 获取 Deployment Token 并访问数据面

| 项 | 值 |
|---|---|
| 结论 | **PASS** |
| 执行时间 | 2026-09-19 15:00:17 |
| 耗时 | 86.1s |

## 测试目的

通过 AcquireDeploymentToken 拿短期 Token，携带 X-Access-Token 访问 https://8080-{dpl}. ap-shanghai.tencentags.com，验证稳定入口按需拉起沙箱并返回内容。

## 前置条件

Deployment dpl-mkbphi9p 为 ACTIVE；工具容器在 8080 监听 HTTP

## 测试步骤与结果

| # | 步骤 | 结论 | 耗时 | 说明 |
|---|------|------|------|------|
| 1 | AcquireDeploymentToken | ✅ PASS | 0.0s | Token 前缀=dpt_zRbYFPUx… ExpiresAt=2026-09-20T07:00:17Z |
| 2 | 数据面返回 200 | ✅ PASS | 0.0s | HTTP 200（尝试 1 次） |
| 3 | 响应为预期的 httpbin JSON 结构 | ✅ PASS | 0.0s | 返回 httpbin 标准结构 |
| 4 | 缺少 X-Access-Token 时应被拒绝 | ✅ PASS | 0.0s | 无 Token 被拒 |

### 证据 1: AcquireDeploymentToken

```
{
  "ExpiresAt": "2026-09-20T07:00:17Z",
  "Token": "dpt_zRbYFPUx95XL696ym22on2FrCUOjHoDGUiKFfhuYny4"
}
```

### 证据 2: 数据面返回 200

```
{
  "url": "https://8080-dpl-mkbphi9p.ap-shanghai.agents.tencentags.com",
  "attempts": 1,
  "last": "HTTP 200",
  "body": "{\n  \"args\": {},\n  \"headers\": {\n    \"Accept\": [\n      \"*/*\"\n    ],\n    \"Accept-Encoding\": [\n      \"gzip, deflate\"\n    ],\n    \"B3\": [\n      \"88504daffd0416f5f44587afe703922c-f3a8a1a3cab5c1c4-1\"\n    ],\n    \"Connection\": [\n      \"upgrade\"\n    ],\n    \"Host\": [\n      \"8080-hpwj7oozi5df35vxj6mlui65twxb6nk37622icxh.ap-shanghai.internal.tencentags.com\"\n    ],\n    \"Traceparent\": [\n      \"00-88504daffd0416f5"
}
```

### 证据 3: 响应为预期的 httpbin JSON 结构

```
{
  "args": {},
  "headers": {
    "Accept": [
      "*/*"
    ],
    "Accept-Encoding": [
      "gzip, deflate"
    ],
    "B3": [
      "88504daffd0416f5f44587afe703922c-f3a8a1a3cab5c1c4-1"
    ],
    "Connection": [
      "upgrade"
    ],
    "Host": [
      "8080-hpwj7oozi5df35vxj6mlui65twxb6nk37622icxh.ap-shanghai.internal.tencentags.com"
    ],
    "Traceparent": [
      "00-88504daffd0416f5
```

### 证据 4: 缺少 X-Access-Token 时应被拒绝

```
{
  "status": 401,
  "body": "{\"code\":\"unauthenticated\",\"message\":\"authentication is required\",\"request_id\":\"QFLW5ERBQBIYSOWAUMFB657R5K\"}\n"
}
```

## 备注

- 数据面 URL: https://8080-dpl-mkbphi9p.ap-shanghai.agents.tencentags.com（HTTP 端口域名规则：{port}-{dpl-id}.{region}.agents.{data-plane-domain}）
