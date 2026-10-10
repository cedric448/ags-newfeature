# AGS 沙箱类型与 AIO 镜像地址调查

> 调查日期：2026-09-28
> 结论：**AGS 的 `aio`（All-In-One）沙箱不对外暴露镜像地址**，且 `ToolType` 中**不存在 `system`** 这个值。

---

## 一、关于 `system`：不是合法的工具类型

实测逐个验证 `ToolType` 枚举：

| 值 | 结果 |
|---|---|
| `browser` | ✅ 可用 |
| `code-interpreter` | ✅ 可用 |
| `custom` | ✅ 可用（需 `CustomConfiguration`） |
| `mobile` | ✅ 可用 |
| `osworld` | ✅ 可用 |
| `swebench` | ✅ 可用 |
| `aio` | ✅ 可用 |
| `android-world` | ✅ 可用 |
| `waa` | ✅ 可用 |
| **`system`** | ❌ `Tool type 'system' is not supported` |
| `computer` | ❌ 不支持 |

传 `system` 会直接报错：

```
[InvalidParameterValue.ToolType] Tool type 'system' is not supported
```

SDK 中的官方枚举（`CreateSandboxToolRequest._ToolType`）：

```
browser / code-interpreter / mobile / osworld /
custom / swebench / aio / android-world / waa
```

**所以「把 aio 改成 system」这个操作无法执行** —— `system` 不是 AGS 的工具类型。
如果你的场景需要「系统级 / 通用计算机」沙箱，对应的类型是 **`osworld`**（桌面操作系统环境）
或 **`mobile`**（移动端），而不是 `system`。

---

## 二、AIO 镜像是平台托管的，查不到地址

我从多个途径尝试获取 `aio` 的镜像地址，**全部无果**：

| 途径 | 结果 |
|---|---|
| `DescribeSystemImages` API（3226 个系统镜像） | 只有 SWE-bench 系列，搜 `aio` / `all-in-one` 均为 0 条 |
| `DescribeSandboxToolList`（`aio` 工具完整定义） | **无 `CustomConfiguration` 字段**，没有 `Image` |
| `DescribeSandboxInstanceList`（实例完整定义） | 只有 `Resources`，无镜像字段 |
| 容器内部（`/`、`/etc`、环境变量、`/opt`） | 无任何镜像标识或构建残留 |
| 官方文档 `132209`（沙箱工具类型说明） | 只说「由平台提供默认的镜像和运行环境」，不给地址 |
| 官方文档 `132210`（CLI 创建） | `CustomConfiguration.Image` 仅适用于 `custom` 类型 |
| AGS 公共 CCR 仓库探测 | 返回 401（需鉴权，无法判断仓库是否存在） |

**对比可以说明问题**：`custom` 类型必须显式传 `Image` 才能创建（我建 DSH 工具时验证过），
而 `aio` 什么都不传就能创建成功 —— 镜像完全由平台管理，用户侧不可见、不可指定。

### 唯一可确认的地址来源

各档位的近似地址如下（**均非 `aio`**，供对照）：

| 用途 | 地址 |
|---|---|
| AGS 公共 code-interpreter 沙箱（我用作 DSH base） | `ccr.ccs.tencentyun.com/ags-image/sandbox-code:latest` |
| AGS 公共 envd 组件 | `ccr.ccs.tencentyun.com/ags-image/envd:v0.2.11` |
| DSH 官方 all-in-one（cookbook） | `ccr.ccs.tencentyun.com/ags.dev/deepseek-harness:v0.1.1-rc.2-ags.4` |
| 你自己的 DSH 镜像 | `euson-tcr.tencentcloudcr.com/cedricbwang/test:v1` |

> ⚠️ 注意区分：cookbook 里的 "all-in-one" 是 **DeepSeek Harness 的 all-in-one**，
> 与 AGS 的 `aio` **工具类型**是两个完全不同的概念。

---

## 三、AIO 沙箱实测内部构成

既然拿不到镜像地址，我把 `aio` 实例跑起来做了完整探测。**基础系统是 Debian 13 (trixie)**，
默认规格 `CPU 4000m / Memory 8192Mi`，用 s6-overlay 管理服务。

### s6 管理的服务（`/etc/s6-overlay/s6-rc.d/`）

```
chromium  envd  envtool  healthd  jupyter  nginx  novnc
ttyd  user  user2  uvicorn  vscode  x11vnc  xvfb
```

### 端口与服务对应

| 端口 | 组件 | 说明 |
|---|---|---|
| **9000** | nginx | **统一入口**，Web 首页标题为 `Sandbox` |
| 8080 | node | Web 服务 |
| 49999 | uvicorn | Python ASGI 服务（AIO 控制面 API） |
| 49984 | ttyd | 浏览器终端 |
| 6901 | websockify | noVNC 代理 |
| 5901 | x11vnc | VNC 服务（配合 xvfb 虚拟显示） |
| 8888 | jupyter-server | Notebook |
| 9222 | chromium | 浏览器 CDP 远程调试 |
| 49985 | python3 | 辅助服务（nginx `/health` 反代到它） |
| 49983 | envd | AGS 数据面（与其他类型一致） |

### nginx 路由（`listen 9000`）

| 路径 | 转发目标 |
|---|---|
| `/health` | `http://127.0.0.1:49985/` |
| `/novnc/` | `http://localhost:6901/` |
| `/cdp/` | `http://localhost:9222/`（浏览器控制） |
| `/websockify` | `http://vnc_proxy/` |
| `/` | 静态页 `/etc/nginx/static` |

### 内置组件版本

- **code-server 4.112.0**（VS Code Web，`/usr/bin/code-server`）
- Jupyter Server + bash_kernel + 完整科学计算栈
- Chromium（CDP 可编程控制）
- s6-overlay v3 进程管理

---

## 四、如果你需要「可控的 AIO 类环境」

有两条路：

### 1. 直接用 `aio` 类型（推荐，零维护）

```bash
# 创建即可，无需任何镜像配置
ToolType: "aio"
NetworkConfiguration: {"NetworkMode": "PUBLIC"}
```

能力全开：代码执行 + 浏览器 + 终端 + 文件系统 + VNC 桌面 + VS Code Web。

### 2. 自建 `custom` 镜像复刻 AIO（可控、可改）

从运行中的 AIO 实例导出配置，打成镜像推到自己的 TCR。已探明的组件清单见上文，
核心是：Debian 13 + nginx(9000) + s6-overlay + ttyd + Jupyter + x11vnc/websockify +
chromium + code-server + envd(49983)。

> 这条路适合需要**改镜像**的场景（加依赖、换版本、预置代码）。
> 只需要「用得爽」的话，用第 1 条就行。

---

## 五、附：`aio` 工具/实例 API 返回样例

**工具定义**（注意没有镜像字段）：
```json
{
  "ToolId": "sdt-4fsi77v2",
  "ToolName": "probe-aio-1790586464",
  "ToolType": "aio",
  "Status": "ACTIVE",
  "NetworkConfiguration": {"NetworkMode": "PUBLIC"},
  "Persistent": false,
  "Tags": [],
  "AccessPolicyIds": []
}
```

**实例定义**（同样没有镜像字段）：
```json
{
  "InstanceId": "aodftgj7z7c7ofdb2erwg4ypilfsgulvdylc2nhr",
  "ToolType": "aio",
  "Status": "RUNNING",
  "CustomConfiguration": {
    "Resources": {"CPU": "4000m", "Memory": "8192Mi", "Storage": ""}
  },
  "NetworkMode": "PUBLIC",
  "AuthMode": "DEFAULT"
}
```

所有探测用的临时工具与实例均已回收。
