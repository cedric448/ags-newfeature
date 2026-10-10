# AGS 数据面文件上传踩坑记录

| 项 | 值 |
|---|---|
| 被测产品 | 腾讯云 Agent Runtime / Agent Sandbox (AGS) 数据面（E2B 兼容协议） |
| 地域 | `ap-beijing`（VPC 模式） |
| E2B SDK | `e2b==2.21.0` / `e2b-code-interpreter==2.6.2` |
| envd | 镜像内 `/usr/bin/envd`（基础镜像 `sandbox-code` 系） |
| 镜像 | `euson-tcr.tencentcloudcr.com/cedricbwang/test:v1` |
| 测试日期 | 2026-10-10 |
| 探针脚本 | `scripts/probe_upload_limit.py`、`scripts/probe_upload_edge.py`、`scripts/chunked_upload.py` |

> 背景：用户反馈用 e2b SDK 往 AGS 沙箱上传文件时遇到 `413 file too large`，
> 需要确认 AGS 数据面（envd `/files` 接口）实际允许的单文件 / 单请求大小上限，
> 并给出绕过方案。

---

## 1. 结论速览

| 项 | 结论 |
|---|---|
| 单次上传请求 body 上限 | **256 MiB**（≥256 MiB 被网关 `stgw` 以 `413` 拒绝） |
| 上限来源 | **腾讯云网关 stgw**（按 `Content-Length` **预判**拒绝），非 envd / 磁盘限制 |
| 失败表现 | 立即返回（~10s 内），报文为 stgw 的 HTML 错误页 |
| 绕过方案 | **客户端手工分片**（SDK 不自动分片），已实测 300 MiB 文件成功（md5 一致） |
| 并发分片 | ❌ **不可行**：AGS 数据面不支持大文件并发上传（见 §4） |
| 大数据吞吐 | 很低且随体积衰减（约 0.2–3 MiB/s），大文件可能撞实例 30m 生命周期 |

---

## 2. 单请求大小上限定位（413 阈值）

### 方法
用 `scripts/probe_upload_limit.py`：几何增长（1 MiB 起 ×2）定位失败点，再二分收敛。
`files.write` 成功后再用 `stat -c %s` 校验落盘大小。

### 实测数据

| 文件大小 | 结果 | 耗时 |
|---|---|---|
| 1 / 2 / 4 / 8 / 16 / 32 MiB | ✅ 成功 | 0.2 – 2.3s |
| 64 MiB | ✅ 成功 | 45s |
| 128 MiB | ✅ 成功 | 215s / 324s（两次） |
| 144 / 160 / 192 / 200 MiB | ✅ 成功 | 275 – 903s |
| **256 MiB** | ❌ **413 Request Entity Too Large** | **10.5s** |

### 关键判据

1. **256 MiB 仅 10.5s 即失败**。按实测吞吐（~3 MiB/s）收完整 body 至少需要 ~85s，
   10.5s 就报错 → **网关在收到请求头、拿到 `Content-Length` 时即判定拒绝**，
   并非“边收边累积、超限才断”。因此 stgw 虽是**流式转发**，但 413 是**前置的大小门限**。
2. 255 MiB 未被瞬时拒绝（网关开始接收 body），200 MiB 明确成功 →
   **上限落在 (200, 256] MiB 区间，硬闸门即 256 MiB**。

### 报错形式

```
e2b.exceptions.SandboxException: 413: <html>
<head><title>413 Request Entity Too Large</title></head>
<body>
<center><h1>413 Request Entity Too Large</h1></center>
<hr><center>stgw</center>
</body>
</html>
```

- 报错体由 **stgw** 返回（HTML），非 envd 的 JSON 错误。
- e2b SDK 对未知状态码统一抛 `SandboxException("<code>: <msg>")`
  （见 `e2b/envd/api.py::format_envd_api_exception`，413 不在默认错误映射中）。
- 日志中还会伴随一次 `RemoteProtocolError: Server disconnected`。

---

## 3. 绕过方案：客户端分片上传

**e2b SDK 的 `files.write` 是整块 body 一次 POST 到 envd `/files`，本身不做自动分片**
（源码见 `e2b/sandbox_sync/filesystem/filesystem.py::write_files`）。
因此大文件必须**客户端手工切片**。

### 思路
1. 把文件切成多个 < 256 MiB 的 chunk（默认 128 MiB，留 50% 余量）；
2. 每片作为一个普通文件上传（`write` 是覆盖写，**不支持 append**，故各片独立命名）；
3. 全部上传后在沙箱内 `cat p0 p1 p2 ... > target` 合并并清理临时片；
4. 校验：每片落盘大小 + 合并后总大小，可选 md5。

### 实现
`scripts/chunked_upload.py`：

```python
from scripts.chunked_upload import chunked_write_file

chunked_write_file(
    sbx,
    local_path="/data/big.iso",
    remote_path="/tmp/big.iso",
    chunk_size=128 * 1024 * 1024,   # 必须 < 256 MiB（代码内强制校验）
    user="root",
    verify_md5=True,
)
```

关键点：
- `chunk_size >= 256 MiB` 直接 `ValueError`；
- 分片名零填充 `p000000`，字典序 = 数字序，`cat p*` 顺序安全；
- 单片上传失败按指数退避重试，并校验落盘字节数；
- 任何异常都会 `rm -rf` 临时目录，不残留。

### 实测结果（PASS）

```
python3 scripts/chunked_upload.py --smoke --size-mib 300 --chunk-mib 128
```

```
[chunk] 1/3  128.0 MiB
[chunk] 2/3  128.0 MiB
[chunk] 3/3   44.0 MiB
[smoke] 上传完成: {'size': 314572800, 'chunks': 3}，耗时 464.5s
[smoke] 本地 md5=083fbb35281def15b748f131968d9778
[smoke] 远端 md5=083fbb35281def15b748f131968d9778
[smoke] 结果: PASS  (文件 300 MiB, 分片 128 MiB)
```

**300 MiB（> 256 MiB 单请求上限）分 3 片成功上传，md5 完全一致** →
证明客户端分片确实能绕过 stgw 的 413。

---

## 4. 并发分片：踩坑（不可行）

按直觉做的“并发分片”版本（多线程各传一片）**在本 AGS 环境全部失败**。

### 实测

| 场景 | 结果 |
|---|---|
| 3 线程 × 128 MiB 并发写 | ❌ 3/3 失败 `Server disconnected` |
| 3 线程 × 32 MiB 并发写 | ❌ 3/3 失败 |
| 2 线程 × 32 MiB 并发写 | ❌ 2/2 失败 |
| 2 线程 × 8 MiB 并发写 | ❌ 2/2 失败 |
| 2 线程 × 8 MiB（octet-stream） | ❌ 2/2 失败 |
| 2 线程 × 1 MiB 并发写 | ❌ 2/2 失败（0.0s 瞬断） |
| 4 线程 × 1 MiB 并发写 | ❌ 4/4 失败 |
| **10 线程 × 1 KB 并发写** | ✅ **0 失败** |

### 关键结论

- **小请求（1 KB）并发 OK，稍大（≥1 MiB）并发即全断** →
  不是客户端线程/连接池问题（连接池 `max_connections=2000` 足够），
  也不是分片大小问题，而是**服务端不接受并发的大 body 上传**。
- 失败形式：`httpx.RemoteProtocolError: Server disconnected`
  （HTTP/2 多路复用下，服务端直接断连）。
- 推测原因：envd 或其前置 stgw 对**并发大请求**（多路复用 stream 同时传 body）
  支持不佳，会重置连接。e2b 传输层 `get_transport()` 固定 `http2=True`
  且为**进程级单例**，多个写请求会复用同一条 HTTP/2 连接的多路复用流。

### 影响与建议

- **不要对大文件上传做多线程并发分片**——会 100% 失败。
- 分片上传请保持**串行**（`scripts/chunked_upload.py` 默认 `concurrency=1`）。
- 需要提速时的可行方向（未逐一实测，供后续验证）：
  - HTTP/1.1 + 多连接（规避 http2 多路复用）是否可用；
  - 改用非数据面通道（对象存储 / COS 中转，沙箱内 `curl` 内网拉取）；
  - 应用层控制并发上限（当前实测连 2 并发都不行，基本无并发空间）。

---

## 5. 吞吐与生命周期

- 上传吞吐**很低且随体积衰减**：~32 MiB 用时 2.3s，64 MiB 45s，200 MiB 903s，
  折算约 **0.2 – 3 MiB/s**。
- 大文件长时间上传可能**撞上实例生命周期**：实测有实例在上传过程中变 `STOPPED`，
  再执行 `commands.run` 报 `Code.unknown / Response 400`。
- 建议：单实例上传总量与单文件大小都要留出时间余量，或把实例 `Timeout` 放大。

---

## 6. 复现方式

```bash
# 1) 定位 413 阈值（几何 + 二分）
python3 scripts/probe_upload_limit.py --hi 256

# 2) 区间内精确探测
python3 scripts/probe_upload_edge.py

# 3) 串行分片上传冒烟（300 MiB / 128 MiB 分片）
python3 scripts/chunked_upload.py --smoke --size-mib 300 --chunk-mib 128

# 4) （反例）并发分片会失败
python3 scripts/chunked_upload.py --smoke --size-mib 300 --chunk-mib 128 --concurrency 3
```

> 所有探针脚本内置 `CleanupRegistry`，结束自动回收实例/工具；
> `AGS_KEEP_RESOURCES=1` 可保留资源排障。

---

## 7. 待确认 / 后续

| 项 | 说明 |
|---|---|
| 255 MiB 结果 | 需补测确认（本次因传输过慢被手动中止，未拿到终态） |
| 上限是否与 envd 版本相关 | 不同基础镜像 envd 版本的 413 阈值是否一致，未验证 |
| 并发失败根因 | 是 envd 还是 stgw 限制、能否通过 HTTP/1.1 或调整连接规避，待验证 |
| `write_files` 批量总大小 | 一次请求多文件时，**总和**是否同样受 256 MiB 约束，未验证 |
