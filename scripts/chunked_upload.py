#!/usr/bin/env python3
"""客户端分片上传示例：绕过 AGS 数据面 stgw 网关 256 MiB 单请求上限。

背景（实测，见 reports / memory）：
- e2b SDK 的 `files.write` 是**整块 body 一次 POST**到 envd `/files` 接口，
  SDK 本身**不做自动分片**。
- 单次请求 body ≥ 256 MiB 会被腾讯云网关 stgw 以 `413 Request Entity Too Large` 直接拒绝
  （按 Content-Length 预判，收到请求头即拒，不是流式累积到超限才拒）。
- 因此大文件必须**客户端手工切片**：把文件切成多个 < 上限的 chunk，
  每片作为一个普通文件上传，最后在沙箱内用 shell 把各片拼接成原文件。

本模块给出可直接复用的分片上传实现，要点：
1. 分片大小默认 128 MiB（留足余量，规避 256 MiB 硬闸门与 multipart 开销）；
2. 每片上传后校验落盘字节数（`stat -c %s`），失败自动重试（指数退避）；
3. 全部片上传完后在沙箱内 `cat p0 p1 p2 ... > target` 合并并删除临时片；
4. 合并后校验总大小，可选校验 md5。

用法（作为库）：
    from scripts.chunked_upload import chunked_write_file, chunked_write_file_concurrent

    # 串行
    chunked_write_file(sbx, "/data/big.iso", "/tmp/big.iso",
                       chunk_size=128 * 1024 * 1024, user="root")

    # 并发（4 个分片同时传）
    chunked_write_file_concurrent(sbx, "/data/big.iso", "/tmp/big.iso",
                                  chunk_size=128 * 1024 * 1024, concurrency=4, user="root")

用法（独立冒烟，需要 AGS 环境，会自动创建/回收沙箱）：
    python3 scripts/chunked_upload.py --smoke --size-mib 300                 # 串行
    python3 scripts/chunked_upload.py --smoke --size-mib 300 --concurrency 4 # 并发
"""
from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import os
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib import CFG, AgsApi, CleanupRegistry, E2B  # noqa: E402

MiB = 1024 * 1024
# 单请求安全上限：stgw 硬闸门 256 MiB，留 50% 余量
DEFAULT_CHUNK = 128 * MiB


# --------------------------------------------------------------------------- #
# 核心：分片上传
# --------------------------------------------------------------------------- #
def _run(sbx, cmd: str, *, user: str, timeout: int = 120) -> tuple[int, str, str]:
    code, out, err = E2B.run(sbx, cmd, user=user, timeout=timeout)
    return code, out, err


def _remote_size(sbx, path: str, *, user: str) -> int | None:
    """返回远端文件字节数；不存在/失败返回 None。"""
    code, out, _ = _run(sbx, f"stat -c %s {path} 2>/dev/null || echo -1", user=user, timeout=30)
    s = out.strip()
    if code == 0 and s.lstrip("-").isdigit() and int(s) >= 0:
        return int(s)
    return None


def _upload_chunk_with_retry(
    sbx,
    data: bytes,
    remote_part: str,
    *,
    user: str,
    retries: int = 3,
    octet_stream: bool = False,
) -> None:
    """上传单个分片，按落盘大小校验，失败重试（指数退避）。"""
    want = len(data)
    last_err: Exception | None = None
    for attempt in range(retries + 1):
        try:
            # files.write 是覆盖写：同一路径重试安全
            sbx.files.write(
                remote_part,
                data,
                user=user,
                request_timeout=900,
                use_octet_stream=octet_stream,
            )
            got = _remote_size(sbx, remote_part, user=user)
            if got == want:
                return
            last_err = RuntimeError(f"落盘大小不一致: 期望 {want}, 实际 {got}")
        except Exception as exc:  # noqa: BLE001 - 统一重试
            last_err = exc
        if attempt < retries:
            time.sleep(2 ** attempt)
    raise RuntimeError(f"分片 {remote_part} 上传失败（已重试 {retries} 次）: {last_err}")


def chunked_write_file(
    sbx,
    local_path: str | os.PathLike,
    remote_path: str,
    *,
    chunk_size: int = DEFAULT_CHUNK,
    user: str = "root",
    octet_stream: bool = False,
    verify_md5: bool = False,
    progress: bool = True,
) -> dict:
    """把本地大文件分片上传到沙箱，并在沙箱内合并成原文件。

    :param sbx:          e2b Sandbox 实例
    :param local_path:   本地源文件
    :param remote_path:  远端目标绝对路径
    :param chunk_size:   分片字节数，必须 < 256 MiB（建议 ≤128 MiB）
    :param user:         远端执行用户（挂载目录常需 root）
    :param octet_stream: 用 application/octet-stream 直传（少一层 multipart 开销）
    :param verify_md5:   合并后校验 md5（大文件会多读一遍远端）
    :return:             包含 size / chunks / md5 等信息的 dict
    """
    if chunk_size >= 256 * MiB:
        raise ValueError("chunk_size 必须 < 256 MiB（stgw 网关上限）")
    if chunk_size <= 0:
        raise ValueError("chunk_size 必须为正")

    local_path = Path(local_path)
    total = local_path.stat().st_size
    n_chunks = max(1, -(-total // chunk_size))  # ceil
    parts_dir = f"/tmp/.chunked_upload_{os.getpid()}_{int(time.time())}"

    if progress:
        print(f"[chunk] 源={local_path} 共 {total} B ({total / MiB:.1f} MiB)，"
              f"分 {n_chunks} 片，每片 {chunk_size / MiB:.0f} MiB")

    # 准备临时目录
    code, _, err = _run(sbx, f"rm -rf {parts_dir} && mkdir -p {parts_dir}", user=user, timeout=60)
    if code != 0:
        raise RuntimeError(f"创建临时目录失败: {err[:200]}")

    part_paths: list[str] = []
    md5 = hashlib.md5() if verify_md5 else None
    uploaded = 0

    try:
        with open(local_path, "rb") as f:
            for idx in range(n_chunks):
                data = f.read(chunk_size)
                if not data:
                    break
                if md5 is not None:
                    md5.update(data)
                part = f"{parts_dir}/p{idx:06d}"
                t0 = time.time()
                _upload_chunk_with_retry(
                    sbx, data, part, user=user, octet_stream=octet_stream
                )
                part_paths.append(part)
                uploaded += len(data)
                if progress:
                    print(f"[chunk] {idx + 1}/{n_chunks}  {len(data) / MiB:7.1f} MiB  "
                          f"{time.time() - t0:6.1f}s  累计 {uploaded / MiB:.1f}/{total / MiB:.1f} MiB")

        # 沙箱内合并：按顺序 cat 所有分片 > 目标文件
        # 注意：cat 参数顺序即拼接顺序，part_paths 已按 idx 递增，安全
        joined = " ".join(part_paths)
        code, _, err = _run(
            sbx,
            f"cat {joined} > {remote_path} && rm -rf {parts_dir}",
            user=user,
            timeout=600,
        )
        if code != 0:
            raise RuntimeError(f"沙箱内合并失败: {err[:300]}")

        # 校验总大小
        got = _remote_size(sbx, remote_path, user=user)
        if got != total:
            raise RuntimeError(f"合并后大小不一致: 期望 {total}, 实际 {got}")

        result = {"remote_path": remote_path, "size": total, "chunks": len(part_paths)}

        if md5 is not None:
            code, out, _ = _run(sbx, f"md5sum {remote_path} | cut -d' ' -f1", user=user, timeout=300)
            remote_md5 = out.strip()
            result["md5_local"] = md5.hexdigest()
            result["md5_remote"] = remote_md5
            result["md5_ok"] = remote_md5 == md5.hexdigest()
            if not result["md5_ok"]:
                raise RuntimeError(f"md5 不一致: local={md5.hexdigest()} remote={remote_md5}")

        if progress:
            print(f"[chunk] 完成 -> {remote_path} ({total} B)，"
                  f"{len(part_paths)} 片{', md5 OK' if verify_md5 else ''}")
        return result

    except Exception:
        # 失败清理临时片，避免残留占空间
        _run(sbx, f"rm -rf {parts_dir}", user=user, timeout=60)
        raise


def chunked_write_bytes(
    sbx,
    data: bytes,
    remote_path: str,
    *,
    chunk_size: int = DEFAULT_CHUNK,
    user: str = "root",
    octet_stream: bool = False,
    progress: bool = True,
) -> dict:
    """内存 bytes 的分片上传（等价物，便于测试，无需落本地文件）。"""
    if chunk_size >= 256 * MiB:
        raise ValueError("chunk_size 必须 < 256 MiB（stgw 网关上限）")
    total = len(data)
    n_chunks = max(1, -(-total // chunk_size))
    parts_dir = f"/tmp/.chunked_upload_{os.getpid()}_{int(time.time())}"
    _run(sbx, f"rm -rf {parts_dir} && mkdir -p {parts_dir}", user=user, timeout=60)

    part_paths: list[str] = []
    try:
        for idx in range(n_chunks):
            chunk = data[idx * chunk_size:(idx + 1) * chunk_size]
            if not chunk:
                break
            part = f"{parts_dir}/p{idx:06d}"
            _upload_chunk_with_retry(sbx, chunk, part, user=user, octet_stream=octet_stream)
            part_paths.append(part)
            if progress:
                print(f"[chunk] {idx + 1}/{n_chunks}  {len(chunk) / MiB:.1f} MiB")
        joined = " ".join(part_paths)
        code, _, err = _run(sbx, f"cat {joined} > {remote_path} && rm -rf {parts_dir}",
                            user=user, timeout=600)
        if code != 0:
            raise RuntimeError(f"合并失败: {err[:300]}")
        got = _remote_size(sbx, remote_path, user=user)
        if got != total:
            raise RuntimeError(f"大小不一致: 期望 {total}, 实际 {got}")
        return {"remote_path": remote_path, "size": total, "chunks": len(part_paths)}
    except Exception:
        _run(sbx, f"rm -rf {parts_dir}", user=user, timeout=60)
        raise


# --------------------------------------------------------------------------- #
# 并发分片上传
# --------------------------------------------------------------------------- #
class _Progress:
    """线程安全的进度计数。"""

    def __init__(self, total_bytes: int, total_chunks: int):
        self.total_bytes = total_bytes
        self.total_chunks = total_chunks
        self.done_chunks = 0
        self.done_bytes = 0
        self._lock = threading.Lock()

    def add(self, nbytes: int, label: str = "") -> None:
        with self._lock:
            self.done_chunks += 1
            self.done_bytes += nbytes
            print(f"[chunk] 完成 {self.done_chunks}/{self.total_chunks}  "
                  f"{nbytes / MiB:7.1f} MiB{label}  "
                  f"累计 {self.done_bytes / MiB:.1f}/{self.total_bytes / MiB:.1f} MiB", flush=True)


def _chunk_jobs_from_bytes(data: bytes, chunk_size: int) -> list[tuple[int, bytes]]:
    n_chunks = max(1, -(-len(data) // chunk_size))
    jobs = []
    for idx in range(n_chunks):
        chunk = data[idx * chunk_size:(idx + 1) * chunk_size]
        if chunk:
            jobs.append((idx, chunk))
    return jobs


def _chunk_jobs_from_file(local_path: Path, chunk_size: int) -> list[tuple[int, bytes]]:
    jobs = []
    with open(local_path, "rb") as f:
        idx = 0
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            jobs.append((idx, chunk))
            idx += 1
    return jobs


def _concurrent_write(
    sbx,
    jobs: list[tuple[int, bytes]],
    remote_path: str,
    *,
    total: int,
    user: str,
    chunk_size: int,
    concurrency: int,
    octet_stream: bool,
    verify_md5: bool,
    data_md5: str | None,
    progress: bool,
) -> dict:
    """jobs = [(idx, chunk_bytes), ...] 并发上传各分片，再在沙箱内合并。"""
    parts_dir = f"/tmp/.chunked_upload_{os.getpid()}_{int(time.time())}"
    code, _, err = _run(sbx, f"rm -rf {parts_dir} && mkdir -p {parts_dir}", user=user, timeout=60)
    if code != 0:
        raise RuntimeError(f"创建临时目录失败: {err[:200]}")

    n_chunks = len(jobs)
    if progress:
        print(f"[chunk] 并发上传：{n_chunks} 片，每片 {chunk_size / MiB:.0f} MiB，"
              f"并发度 {concurrency}")

    prog = _Progress(total, n_chunks)
    failures: list[tuple[int, Exception]] = []
    lock = threading.Lock()

    def worker(idx: int, chunk: bytes) -> None:
        part = f"{parts_dir}/p{idx:06d}"
        try:
            _upload_chunk_with_retry(sbx, chunk, part, user=user, octet_stream=octet_stream)
            if progress:
                prog.add(len(chunk), f"  (片 #{idx})")
        except Exception as exc:  # noqa: BLE001 - 汇总后统一抛
            with lock:
                failures.append((idx, exc))

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as pool:
            futures = [pool.submit(worker, idx, chunk) for idx, chunk in jobs]
            for fut in concurrent.futures.as_completed(futures):
                fut.result()  # worker 已吞异常，这里只为传播意外错误

        if failures:
            detail = "; ".join(f"#{i}: {e}" for i, e in failures[:5])
            raise RuntimeError(f"{len(failures)} 个分片上传失败：{detail}")

        # 沙箱内按 idx 顺序合并
        part_paths = [f"{parts_dir}/p{idx:06d}" for idx, _ in sorted(jobs)]
        joined = " ".join(part_paths)
        code, _, err = _run(sbx, f"cat {joined} > {remote_path} && rm -rf {parts_dir}",
                            user=user, timeout=900)
        if code != 0:
            raise RuntimeError(f"沙箱内合并失败: {err[:300]}")

        got = _remote_size(sbx, remote_path, user=user)
        if got != total:
            raise RuntimeError(f"合并后大小不一致: 期望 {total}, 实际 {got}")

        result = {"remote_path": remote_path, "size": total, "chunks": n_chunks,
                  "concurrency": concurrency}
        if verify_md5 and data_md5 is not None:
            code, out, _ = _run(sbx, f"md5sum {remote_path} | cut -d' ' -f1", user=user, timeout=600)
            result["md5_local"] = data_md5
            result["md5_remote"] = out.strip()
            result["md5_ok"] = out.strip() == data_md5
            if not result["md5_ok"]:
                raise RuntimeError(f"md5 不一致: local={data_md5} remote={out.strip()}")
        return result
    except Exception:
        _run(sbx, f"rm -rf {parts_dir}", user=user, timeout=60)
        raise


def chunked_write_file_concurrent(
    sbx,
    local_path: str | os.PathLike,
    remote_path: str,
    *,
    chunk_size: int = DEFAULT_CHUNK,
    concurrency: int = 4,
    user: str = "root",
    octet_stream: bool = False,
    verify_md5: bool = False,
    progress: bool = True,
) -> dict:
    """文件版并发分片上传。

    :param concurrency: 并发上传的分片数（线程数）。受实例带宽/网关限流约束，
                        建议 4~8；过高可能触发限流反而更慢。
    其余参数同 chunked_write_file。
    """
    if chunk_size >= 256 * MiB:
        raise ValueError("chunk_size 必须 < 256 MiB（stgw 网关上限）")
    if concurrency < 1:
        raise ValueError("concurrency 必须 ≥ 1")

    local_path = Path(local_path)
    total = local_path.stat().st_size
    data_md5 = hashlib.md5(local_path.read_bytes()).hexdigest() if verify_md5 else None
    jobs = _chunk_jobs_from_file(local_path, chunk_size)
    if progress:
        print(f"[chunk] 源={local_path} 共 {total} B ({total / MiB:.1f} MiB)")
    return _concurrent_write(
        sbx, jobs, remote_path, total=total, user=user, chunk_size=chunk_size,
        concurrency=min(concurrency, len(jobs)) or 1, octet_stream=octet_stream,
        verify_md5=verify_md5, data_md5=data_md5, progress=progress,
    )


def chunked_write_bytes_concurrent(
    sbx,
    data: bytes,
    remote_path: str,
    *,
    chunk_size: int = DEFAULT_CHUNK,
    concurrency: int = 4,
    user: str = "root",
    octet_stream: bool = False,
    progress: bool = True,
) -> dict:
    """内存 bytes 版并发分片上传（便于测试）。"""
    if chunk_size >= 256 * MiB:
        raise ValueError("chunk_size 必须 < 256 MiB（stgw 网关上限）")
    if concurrency < 1:
        raise ValueError("concurrency 必须 ≥ 1")
    total = len(data)
    jobs = _chunk_jobs_from_bytes(data, chunk_size)
    return _concurrent_write(
        sbx, jobs, remote_path, total=total, user=user, chunk_size=chunk_size,
        concurrency=min(concurrency, len(jobs)) or 1, octet_stream=octet_stream,
        verify_md5=False, data_md5=None, progress=progress,
    )

# --------------------------------------------------------------------------- #
# 冒烟：端到端验证分片上传确实能突破 256 MiB
# --------------------------------------------------------------------------- #
ENVD_CMD = "/usr/bin/envd -port 49983"


def _build_tool_payload(name: str, image: str) -> dict:
    return {
        "ToolName": name, "ToolType": "custom", "Description": "分片上传冒烟",
        "NetworkConfiguration": CFG.vpc_network(), "DefaultTimeout": "30m", "RoleArn": CFG.role_arn,
        "CustomConfiguration": {
            "Image": image, "ImageRegistryType": CFG.image_registry_type,
            "Command": ["sh"], "Args": ["-c", ENVD_CMD],
            "Ports": [{"Name": "envd", "Port": 49983, "Protocol": "TCP"}],
            "Resources": {"CPU": "2000m", "Memory": "4096Mi"},
            "Probe": {"HttpGet": {"Path": "/health", "Port": 49983, "Scheme": "HTTP"},
                      "ReadyTimeoutMs": 30000, "ProbeTimeoutMs": 2000, "ProbePeriodMs": 3000,
                      "SuccessThreshold": 1, "FailureThreshold": 100},
        },
    }


def _smoke(size_mib: int, chunk_mib: int, concurrency: int = 1) -> int:
    ags = AgsApi()
    cleanup = CleanupRegistry(keep=CFG.keep_resources)
    tool_name = f"{CFG.run_prefix}-chunk-{int(time.time())}"
    print(f"[smoke] 创建工具 {tool_name} ...")
    tool_id = ags.create_tool(_build_tool_payload(tool_name, CFG.image)).get("ToolId")
    cleanup.tool(ags, tool_id)
    ags.wait_tool(tool_id, want="ACTIVE", timeout=600)

    resp = ags.start_instance({"ToolName": tool_name, "Timeout": "30m"})
    iid = (resp.get("Instance") or {}).get("InstanceId") or resp.get("InstanceId")
    cleanup.instance(ags, iid)
    ags.wait_instance(iid, want="RUNNING", timeout=900)
    print(f"[smoke] 实例 RUNNING {iid}")

    sbx = E2B.create(tool_name, timeout=1800)
    cleanup.sandbox(sbx)
    print(f"[smoke] E2B 连接 {sbx.sandbox_id}")

    # 用可复现的伪随机数据，便于校验
    import random
    rnd = random.Random(42)
    payload = bytes(rnd.getrandbits(8) for _ in range(size_mib * MiB))
    local_md5 = hashlib.md5(payload).hexdigest()

    mode = "并发" if concurrency > 1 else "串行"
    t0 = time.time()
    if concurrency > 1:
        res = chunked_write_bytes_concurrent(
            sbx, payload, "/tmp/big.bin",
            chunk_size=chunk_mib * MiB, concurrency=concurrency, user="root", progress=True)
    else:
        res = chunked_write_bytes(sbx, payload, "/tmp/big.bin",
                                  chunk_size=chunk_mib * MiB, user="root", progress=True)
    elapsed = time.time() - t0
    print(f"[smoke] {mode}上传完成: {res}，耗时 {elapsed:.1f}s "
          f"(吞吐 {size_mib / elapsed:.2f} MiB/s)")

    code, out, _ = E2B.run(sbx, "md5sum /tmp/big.bin | cut -d' ' -f1", user="root", timeout=600)
    remote_md5 = out.strip()
    ok = remote_md5 == local_md5 and res["size"] == size_mib * MiB
    print(f"[smoke] 本地 md5={local_md5}")
    print(f"[smoke] 远端 md5={remote_md5}")
    print(f"[smoke] 结果: {'PASS' if ok else 'FAIL'}  "
          f"(文件 {size_mib} MiB, 分片 {chunk_mib} MiB, 并发度 {concurrency})")
    E2B.kill(sbx)
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="AGS 客户端分片上传示例/冒烟")
    ap.add_argument("--smoke", action="store_true", help="端到端冒烟（会自动建/删沙箱）")
    ap.add_argument("--size-mib", type=int, default=300, help="冒烟文件大小 MiB（默认 300，>256 才有意义）")
    ap.add_argument("--chunk-mib", type=int, default=128, help="分片大小 MiB（默认 128）")
    ap.add_argument("--concurrency", type=int, default=1,
                    help="并发分片数（默认 1=串行；>1 走并发版本，建议 4~8）")
    args = ap.parse_args()
    if args.smoke:
        return _smoke(args.size_mib, args.chunk_mib, args.concurrency)
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
