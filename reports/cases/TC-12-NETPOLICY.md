# TC-12 AGS 网络代理 + NetworkPolicy 测试

| 项 | 值 |
|---|---|
| 测试例编号 | TC-12 |
| 测试目标 | VPC 工具 + 本机代理出网 + x-network-policy 禁网/放行 |
| 地域 | `ap-beijing`（子网 `subnet-heh2tv3n` / `ap-beijing-6`） |
| 代理 | `172.21.80.142:1087`（本机内网 IP，v2ray HTTP 代理） |
| 参考文档 | `networkpolicy-docs 3/docs/networkpolicy-e2b-configuration.md` |
| 脚本 | `scripts/tc12_netpolicy.py` |
| 原始数据 | `reports/artifacts/tc12-netpolicy.json` |
| 结论 | ⚠️ **代理链路 5/5 通过；NetworkPolicy 未对本账号开通** |

---

## 1. 检查点结果

| # | 检查项 | 结果 | 实测 |
|---|---|---|---|
| 1 | VPC 网络类型 Tool 创建成功 | ✅ PASS | `NetworkMode=VPC`，自动分配 `NetworkConnectorId` |
| 2 | 沙箱可连通本机代理端口 | ✅ PASS | `172.21.80.142:1087` TCP 可达 |
| 3 | 经代理出网成功 | ✅ PASS | HTTP 204，0.37s |
| 4 | 代理出口为香港 | ✅ PASS | `43.135.74.4` / `Hong Kong` |
| 5 | 直连（不经代理）不可达 | ✅ PASS | 超时（符合预期） |
| 6 | 创建时 `x-network-policy=deny-all` 生效 | ❌ **FAIL** | 账号未开通（见第 4 节） |

---

## 2. VPC 工具与子网选择（关键前置）

### 2.1 为什么必须选对本子网

沙箱要访问本机代理，**必须与本机处于同一 VPC 子网**。初次使用已有 VPC 工具
（`subnet-2sockuph` / `10.35.88.0/24`）时失败，原因是：

| 项 | 旧工具 | 本机 |
|---|---|---|
| 子网 | `10.35.88.0/24`（`vpc-btu1jjqg`） | `172.21.80.0/20`（`vpc-ovochv3a`） |
| 沙箱内地址 | `169.254.68.6`（链路本地） | `172.21.80.142` |
| 网关 | `169.254.68.5` | `172.21.80.1` |
| 访问代理 | ❌ TCP FAIL | — |

即使用 VPC 模式，不同子网之间仍被 NetworkConnector 隔离，**无法互通**。

### 2.2 正确配置

通过 VPC API 反查本机 IP 归属：

```
本机 172.21.80.142 → vpc-ovochv3a (Default-VPC 172.21.0.0/16)
                   → subnet-heh2tv3n (172.21.80.0/20, ap-beijing-6)  ← 本机所在子网
```

使用该子网创建工具后，沙箱虽仍显示 `169.254.68.6`，但**经 NetworkConnector 可正常路由到 172.21.x.x**：

```json
{
  "NetworkMode": "VPC",
  "VpcConfig": {
    "SubnetIds": ["subnet-heh2tv3n"],
    "SecurityGroupIds": ["sg-p3sxc9y3"],
    "NetworkConnectorId": "nc-ljakt1wo"
  }
}
```

---

## 3. 代理链路验证

### 3.1 代理侧配置

v2ray 默认只监听 `127.0.0.1`，沙箱无法访问。已改为监听本机内网 IP：

```
inbound socks  127.0.0.1:1080  →  172.21.80.142:1080
inbound http   127.0.0.1:1087  →  172.21.80.142:1087
```

> 修改前已备份原配置至 `config.json.bak.<timestamp>`。

### 3.2 沙箱内实测

| 检查 | 结果 |
|---|---|
| TCP 连通 `172.21.80.142:1087` | ✅ OK |
| `curl -x http://172.21.80.142:1087 http://www.gstatic.com/generate_204` | ✅ **204** / 0.37s |
| `curl -x ... https://ipinfo.io/json` | ✅ `"ip": "43.135.74.4"`, `"city": "Hong Kong"` |
| 不经代理直连 `gstatic` | ❌ 超时（符合预期，沙箱无公网出口） |

**结论：AGS 沙箱经本机内网代理成功访问外网，出口确认为香港。**

三次延迟采样：0.389s / 0.894s / 0.339s。

---

## 4. NetworkPolicy：账号未开通（阻塞项）

### 4.1 三条路径全部被同一错误拦截

| 路径 | 调用方式 | 结果 |
|---|---|---|
| E2B 兼容创建 | `Sandbox.create(metadata={"x-network-policy": ...})` | ❌ 拦截 |
| 原生实例级 | `StartSandboxInstance(NetworkPolicy=...)` | ❌ 拦截 |
| 原生工具级 | `CreateSandboxTool(NetworkPolicy=...)` | ❌ 拦截 |
| 原生更新 | `UpdateSandboxInstance(NetworkPolicy=...)` | ❌ 拦截 |

统一错误：

```
[UnsupportedOperation.SandboxTool]
NetworkPolicy is not enabled for this account (tool_id=sdt-xxx)
```

### 4.2 根因：灰度白名单

参考文档 `networkpolicy-field-reference.md` 明确说明：

> 只要请求里显式带了 `NetworkPolicy`，服务端会**先检查 NetworkPolicy 白名单**。
> 未命中白名单时，请求会被拒绝，不会进入策略下发流程。

`networkpolicy-zeroproxy-relationship.md` 进一步说明：

> `NetworkPolicy` 只有在白名单命中时才允许创建或更新。
> `networkPolicyEnabled` 要求 `instance.NetworkPolicy != nil`、AIO 白名单、
> 且 `rainbow IsNetworkPolicyWhitelisted` 匹配。

**故本测试例的第 6 项无法继续，需要先为该账号（UIN `100008634787`）开通 NetworkPolicy 灰度。**

### 4.3 一个易混淆点：原生 metadata 不识别 `x-network-policy`

用**原生** `StartSandboxInstance` 传：

```json
{"Metadata": [{"Name": "x-network-policy", "Value": "{\"DefaultDecision\":\"deny\",\"Rules\":[]}"}]}
```

结果：

- `NetworkPolicy` 字段回读为 **`null`**
- 该 key 被当作**普通 metadata** 原样保留
- **策略完全未生效**，代理请求照样返回 204

> `x-network-policy` 的映射逻辑只存在于 **E2B 兼容控制面**（`POST /sandboxes`），
> 原生 `StartSandboxInstance` 不解析它。这是容易踩的坑。

---

## 5. 待开通后的验证步骤

账号开通 NetworkPolicy 白名单后，直接运行：

```bash
python3 scripts/tc12_netpolicy.py
```

脚本会自动完成完整场景：

1. 创建 VPC 工具（同子网）
2. **E2B 创建沙箱时带 `x-network-policy` = `{"DefaultDecision":"deny","Rules":[]}`**
3. 验证 deny-all 下代理被阻断
4. `UpdateSandboxInstance(NetworkPolicy={"DefaultDecision":"allow","Rules":[]})` 改为 allow-all
5. 验证代理恢复（HTTP 204）

---

## 6. 结论

| 项 | 结论 |
|---|---|
| VPC 工具创建 | ✅ 可用，需选同子网 |
| 沙箱经本机代理出网 | ✅ 成功，出口香港 |
| 无代理时沙箱出网 | ✅ 被阻断（VPC 模式无公网出口） |
| **NetworkPolicy deny-all / PATCH allow-all** | ⚠️ **受阻：账号未开通灰度白名单** |

**代理链路已完整打通并验证；NetworkPolicy 部分因账号未被纳入灰度而无法验证，
需要平台开通后才能完成本测试例的完整闭环。**

---

## 7. 复现方式

```bash
# 完整测试
python3 scripts/tc12_netpolicy.py --proxy-ip 172.21.80.142 --proxy-port 1087

# 只验证代理链路（跳过 NetworkPolicy）
python3 scripts/tc12_netpolicy.py --probe-only

# 指定其他子网/安全组
python3 scripts/tc12_netpolicy.py --subnet subnet-xxx --sg sg-xxx
```
