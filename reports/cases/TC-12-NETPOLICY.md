# TC-12 AGS 网络代理 + NetworkPolicy 测试

| 项 | 值 |
|---|---|
| 测试例编号 | TC-12 |
| 测试目标 | VPC 工具 + 本机代理出网 + `x-network-policy` 禁网/放行闭环 |
| 地域 | `ap-beijing`（子网 `subnet-heh2tv3n` / `ap-beijing-6`） |
| 代理 | `172.21.80.142:1087`（本机内网 IP，v2ray HTTP 代理） |
| 参考文档 | `networkpolicy-docs 3/docs/` |
| 脚本 | `scripts/tc12_netpolicy.py` |
| 原始数据 | `reports/artifacts/tc12-netpolicy.json` |
| 结论 | ✅ **PASS 11/11** |

---

## 1. 检查点结果

| # | 检查项 | 结果 | 实测 |
|---|---|---|---|
| 1 | VPC 网络类型 Tool 创建成功 | ✅ PASS | `NetworkMode=VPC`，自动分配 `NetworkConnectorId` |
| 2 | 沙箱可连通本机代理端口 | ✅ PASS | `172.21.80.142:1087` TCP 可达 |
| 3 | 基线（无策略）经代理出网 | ✅ PASS | **204** |
| 4 | 基线代理出口为香港 | ✅ PASS | `43.135.74.4 / Hong Kong` |
| 5 | 基线直连公网不可达 | ✅ PASS | 超时（VPC 无公网出口） |
| 6 | 创建时 `x-network-policy=deny-all` 已下发 | ✅ PASS | 回读 `{"DefaultDecision":"deny"}` |
| 7 | deny-all 下 HTTPS 出网被阻断 | ✅ PASS | **403** |
| 8 | deny-all 返回 `No policy rule matched` | ✅ PASS | `No policy rule matched the request` |
| 9 | **PATCH 为 allow-all 后 HTTPS 恢复** | ✅ PASS | **204，10 秒生效** |
| 10 | allow-all 下 HTTP 出网成功 | ✅ PASS | **200** |
| 11 | **allow-all 后出口仍为香港** | ✅ PASS | `43.135.74.4 / Hong Kong` |

---

## 2. 完整测试流程

```
① 创建 VPC Tool（subnet-heh2tv3n，与本机同子网）
      ↓
② 基线实例（无策略）：curl -x 本机代理 → 204 / 香港  ✅
      ↓
③ E2B 创建沙箱，metadata[x-network-policy] = deny-all
      ↓  回读 NetworkPolicy = {DefaultDecision: deny}
④ 验证禁网：HTTPS → 403 No policy rule matched  ✅
      ↓
⑤ UpdateSandboxInstance(NetworkPolicy = allow-all + upstream)
      ↓  10 秒内生效
⑥ 验证联网：HTTPS → 204，HTTP → 200，出口 香港  ✅
```

---

## 3. 关键发现（重要）

### 3.1 启用 NetworkPolicy 后，`curl -x 代理` 不再可用

这是本次测试最反直觉的一点。同样一条命令：

| 场景 | `curl -x http://172.21.80.142:1087 ...` |
|---|---|
| **无 NetworkPolicy** | ✅ **204** |
| **allow-all** | ❌ **400** |
| **deny-all** | ❌ 403 |

原因：NetworkPolicy 会拉起 **zeroproxy sidecar**，它通过 iptables 把**沙箱内全部 TCP 流量**
重定向到本地 sidecar（`AIOSidecarPort = 57890`）。沙箱进程发起的「连到外部代理」的请求，
会被 sidecar 自身拦截并改写，无法按原始 HTTP 代理语义送达。

### 3.2 正确做法：`Decision=upstream` + `ForwardProxy=true`

要让流量经本机代理出去，必须在策略里声明 upstream，而不是在进程里设 `-x`：

```json
{
  "DefaultDecision": "allow",
  "Rules": [{
    "Name": "forward-all-via-local-proxy",
    "Decision": "upstream",
    "Resources": [{ "Hosts": ["*"] }],
    "UpstreamConfig": {
      "Host": "172.21.80.142",
      "Scheme": "http",
      "Port": 1087,
      "ForwardProxy": true
    }
  }]
}
```

**`ForwardProxy=true` 是必要条件。** 文档描述：

> 开启后按 HTTP forward proxy 语义转发 upstream 流量：HTTP 使用 absolute-form，
> HTTPS/CONNECT 通过上游代理建隧道。

### 3.3 缺少 `ForwardProxy` 时的错误码（排查过程）

| 配置 | 结果 | 原因 |
|---|---|---|
| upstream 无 ForwardProxy，Scheme=http | **400** | 上游收到原始 HTTP，v2ray 按代理协议解析失败 |
| upstream 无 ForwardProxy，Scheme=https | **502** | 上游收到原始 TLS ClientHello |
| `Host` 写成 `IP:port` | **500** | Host 字段不接受端口后缀 |
| Headers 无 ForwardProxy | **400 报错** | `Headers is only valid when ForwardProxy is true` ← 该报错直接暴露正解 |

v2ray 日志佐证：

```
[Warning] proxy/http: failed to read http request > malformed HTTP request "\x16\x03\x01..."
```

即上游收到的是 **TLS 握手字节**而非 HTTP 代理请求。

### 3.4 子网必须与本机一致

初次尝试复用已有 VPC 工具（`subnet-2sockuph` / `10.35.88.0/24`）失败：

| 项 | 旧工具 | 本机 |
|---|---|---|
| 子网 | `10.35.88.0/24` | `172.21.80.0/20`（`vpc-ovochv3a`） |
| 沙箱网关 | `169.254.68.5` | `172.21.80.1` |
| 访问代理 | ❌ TCP FAIL | — |

**同为 VPC 模式，不同子网之间仍被 NetworkConnector 隔离。** 实测通过 VPC API 反查本机归属子网，
确认使用 `subnet-heh2tv3n` 后可达。

### 3.5 PATCH 生效时间约 10 秒

`UpdateSandboxInstance` 调用后，策略经 `cubeproxy -> AIO sidecar -> zeroproxy` 下发，
实测 **10 秒内生效**。脚本按 10 秒间隔轮询，最多等待 90 秒。

---

## 4. 环境准备

### 4.1 代理监听内网 IP

v2ray 默认只监听 `127.0.0.1`，沙箱无法访问。已改为监听本机内网 IP：

```
inbound socks  127.0.0.1:1080  ->  172.21.80.142:1080
inbound http   127.0.0.1:1087  ->  172.21.80.142:1087
```

原配置已备份至 `/usr/local/etc/v2ray/config.json.bak.<timestamp>`。

### 4.2 前置条件

| 项 | 说明 |
|---|---|
| 账号 NetworkPolicy 白名单 | **必须开通**，否则所有路径返回 `NetworkPolicy is not enabled for this account` |
| VPC 子网 | 必须与本机测试机同子网 |
| HAVIP 配额 | 每个 VPC 工具占用一个，配额不足报 `ResourceInsufficient.HAVIPQuota` |

---

## 5. 结论

| 能力 | 结论 |
|---|---|
| VPC 网络类型 Tool | ✅ 可用（需同子网） |
| 沙箱经本机代理出网 | ✅ 成功，出口香港 |
| `x-network-policy` deny-all 禁网 | ✅ 403 阻断 |
| PATCH 改 allow-all 联网 | ✅ 10 秒生效，恢复 204/200 |
| allow-all 经本机代理转发 | ✅ 需 `ForwardProxy=true` |

**开启 NetworkPolicy 后沙箱的出网模型发生根本变化：进程内直接使用 `-x` 代理无效，
必须通过 `Decision=upstream` + `UpstreamConfig.ForwardProxy=true` 在策略层声明代理。
这是使用本能力时最关键的一条实践约束。**

---

## 6. 复现方式

```bash
# 完整闭环（deny-all -> PATCH allow-all -> 验证）
python3 scripts/tc12_netpolicy.py --proxy-ip 172.21.80.142 --proxy-port 1087

# 只验证代理链路（不含 NetworkPolicy）
python3 scripts/tc12_netpolicy.py --probe-only
```
