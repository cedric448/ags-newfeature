#!/usr/bin/env python3
"""TC-05 探针：e2b SDK files.write 上传大小上限（413 阈值定位）。

背景：用户反馈用 e2b SDK 往 AGS 沙箱上传文件时遇到 `413 file too large`，
需要确认 AGS 数据面（envd `/files` 接口）实际允许的**最大单文件大小**。

方法：
1. 用状态为 ACTIVE 的既有工具（或新建一个）启动沙箱实例；
2. 通过 `sbx.files.write(path, bytes)` 上传一系列递增大小的文件，
   从 1 MiB 起按 2 倍增长，遇到失败后二分收敛，定位精确阈值；
3. 记录成功/失败边界、HTTP 状态码、异常类型与报文。

用法：
    python3 scripts/probe_upload_limit.py                 # 自动新建工具并探针
    python3 scripts/probe_upload_limit.py --tool <ToolName>   # 复用已有工具
    python3 scripts/probe_upload_limit.py --mode vpc      # 网络模式：vpc(默认)/public
    python3 scripts/probe_upload_limit.py --lo 1 --hi 512 # 自定义搜索区间（MiB）
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib import CFG, AgsApi, CleanupRegistry, E2B  # noqa: E402

ENVD_CMD = "/usr/bin/envd -port 49983"
MiB = 1024 * 1024


def build_tool_payload(name: str, image: str, network: dict) -> dict:
    return {
        "ToolName": name,
        "ToolType": "custom",
        "Description": "AGS 上传大小上限探针",
        "NetworkConfiguration": network,
        "DefaultTimeout": "30m",
        "RoleArn": CFG.role_arn,
        "CustomConfiguration": {
            "Image": image,
            "ImageRegistryType": CFG.image_registry_type,
            "Command": ["sh"],
            "Args": ["-c", ENVD_CMD],
            "Ports": [{"Name": "envd", "Port": 49983, "Protocol": "TCP"}],
            "Resources": {"CPU": "2000m", "Memory": "4096Mi"},
            "Probe": {
                "HttpGet": {"Path": "/health", "Port": 49983, "Scheme": "HTTP"},
                "ReadyTimeoutMs": 30000,
                "ProbeTimeoutMs": 2000,
                "ProbePeriodMs": 3000,
                "SuccessThreshold": 1,
                "FailureThreshold": 100,
            },
        },
    }


class Probe:
    """上传探针：对指定字节数执行一次 files.write，捕获结果。"""

    def __init__(self, sbx, remote_dir: str = "/tmp/upload-probe"):
        self.sbx = sbx
        self.dir = remote_dir
        self.results: list[dict] = []

    def try_size(self, nbytes: int, *, use_octet_stream: bool = False) -> dict:
        payload = b"\x00" * nbytes
        path = f"{self.dir}/{nbytes}.bin"
        t0 = time.time()
        rec = {"bytes": nbytes, "mib": round(nbytes / MiB, 3),
               "octet_stream": use_octet_stream, "ok": False, "error": None,
               "error_type": None, "status_code": None, "elapsed": None}
        try:
            self.sbx.files.write(path, payload, user="root",
                                 request_timeout=600, use_octet_stream=use_octet_stream)
            # 读回校验真实落盘大小
            _, out, _ = E2B.run(self.sbx, f"stat -c %s {path}", user="root", timeout=60)
            actual = out.strip()
            rec["ok"] = True
            rec["actual_bytes"] = int(actual) if actual.isdigit() else None
        except Exception as exc:  # noqa: BLE001
            rec["error"] = str(exc)[:400]
            rec["error_type"] = type(exc).__name__
            # e2b 对未知状态码会抛 SandboxException("413: <msg>")
            msg = str(exc)
            for code in ("413", "400", "401", "404", "429", "502", "507"):
                if msg.startswith(f"{code}:") or f"{code}:" in msg[:40]:
                    rec["status_code"] = int(code)
                    break
        finally:
            rec["elapsed"] = round(time.time() - t0, 2)
        # 清理远端文件，避免占满磁盘
        E2B.run(self.sbx, f"rm -f {path}", user="root", timeout=30)
        self.results.append(rec)
        self._log(rec)
        return rec

    def _log(self, rec: dict) -> None:
        mark = "OK " if rec["ok"] else "ERR"
        detail = (f"actual={rec.get('actual_bytes')}" if rec["ok"]
                  else f"{rec['error_type']}: {rec['error']}")
        flag = " octet-stream" if rec["octet_stream"] else ""
        print(f"  [{mark}] {rec['mib']:>10} MiB ({rec['bytes']} B){flag} "
              f"{rec['elapsed']:>6.1f}s  {detail}")

    # ---------------- 搜索策略 ----------------

    def geometric(self, start_mib: float, max_mib: float) -> tuple[bool, int | None]:
        """从 start 起按 2 倍增长直到失败，返回 (找到失败, 首个失败字节数)。"""
        print(f"\n[阶段1] 几何增长：{start_mib} MiB → {max_mib} MiB（×2）")
        size = int(start_mib * MiB)
        cap = int(max_mib * MiB)
        last_ok = None
        while size <= cap:
            rec = self.try_size(size)
            if rec["ok"]:
                last_ok = size
                size *= 2
            else:
                return True, size
        print(f"  未达上限（最大成功 {last_ok} B = {last_ok / MiB:.1f} MiB），可调高 --hi")
        return False, None

    def bisect(self, lo_ok: int, hi_fail: int, *, octet_stream: bool = False,
               granularity: int = 1) -> tuple[int, int]:
        """在 (lo_ok, hi_fail] 内二分，返回 (最大成功, 最小失败)。"""
        print(f"\n[阶段2] 二分收敛：成功={lo_ok} B / 失败={hi_fail} B"
              f"{'（octet-stream）' if octet_stream else ''}")
        while hi_fail - lo_ok > granularity:
            mid = (lo_ok + hi_fail) // 2
            rec = self.try_size(mid, use_octet_stream=octet_stream)
            if rec["ok"]:
                lo_ok = mid
            else:
                hi_fail = mid
        return lo_ok, hi_fail


def pretty(n: int | None) -> str:
    if not n:
        return "—"
    return f"{n} B ({n / MiB:.3f} MiB)"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tool", default=None, help="复用已存在的 ToolName（须为 ACTIVE）")
    ap.add_argument("--mode", choices=["vpc", "public"], default="vpc")
    ap.add_argument("--lo", type=float, default=1.0, help="几何搜索起点 MiB")
    ap.add_argument("--hi", type=float, default=512.0, help="几何搜索上限 MiB")
    ap.add_argument("--skip-bisect", action="store_true", help="只做几何定位，不二分")
    ap.add_argument("--octet-stream", action="store_true", help="全部使用 octet-stream 上传")
    args = ap.parse_args()

    network = CFG.vpc_network() if args.mode == "vpc" else CFG.public_network()
    ags = AgsApi()
    cleanup = CleanupRegistry(keep=CFG.keep_resources)

    tool_name = args.tool
    created_tool = False
    sbx = None

    print(f"=== AGS 上传大小上限探针 ===")
    print(f"region={ags.region}  domain={CFG.e2b_domain}  mode={args.mode}  image={CFG.image}")

    # ---- 准备工具 ----
    if tool_name:
        tool = ags.find_tool_by_name(tool_name)
        if not tool:
            print(f"!! 未找到工具 {tool_name}")
            return 2
        if tool.get("Status") != "ACTIVE":
            print(f"!! 工具 {tool_name} 状态 {tool.get('Status')}，非 ACTIVE")
            return 2
        print(f"[工具] 复用 {tool_name} (ToolId={tool.get('ToolId')})")
    else:
        tool_name = f"{CFG.run_prefix}-probe-{int(time.time())}"
        print(f"[工具] 创建 {tool_name} ...")
        payload = build_tool_payload(tool_name, CFG.image, network)
        resp = ags.create_tool(payload)
        tool_id = resp.get("ToolId")
        cleanup.tool(ags, tool_id)
        created_tool = True
        ags.wait_tool(tool_id, want="ACTIVE", timeout=600)
        print(f"[工具] ACTIVE (ToolId={tool_id})")

    # ---- 启动沙箱 ----
    try:
        print("[实例] 启动中 ...")
        resp = ags.start_instance({"ToolName": tool_name, "Timeout": "30m"})
        instance_id = (resp.get("Instance") or {}).get("InstanceId") or resp.get("InstanceId")
        cleanup.instance(ags, instance_id)
        ags.wait_instance(instance_id, want="RUNNING", timeout=900)
        print(f"[实例] RUNNING (InstanceId={instance_id})")

        sbx = E2B.create(tool_name, timeout=1800)
        cleanup.sandbox(sbx)
        print(f"[E2B ] 已连接 sandbox_id={sbx.sandbox_id}")

        probe = Probe(sbx)
        # 记录环境与 envd 版本（若可获得）
        code, out, err = E2B.run(sbx, "uname -a; df -h / | tail -1", user="root", timeout=30)
        print(f"[环境] {out.strip()}")

        if args.octet_stream:
            print("\n[模式] 全程使用 application/octet-stream 上传")

        # ---- 阶段 1：几何定位 ----
        found, first_fail = probe.geometric(args.lo, args.hi)

        max_ok = None
        min_fail = None
        if not found:
            if probe.results:
                max_ok = max((r["bytes"] for r in probe.results if r["ok"]), default=None)
            print("\n未能触发失败，无法定位上限。")
        else:
            # 最后一个成功值即为 lo
            oks = [r["bytes"] for r in probe.results if r["ok"] and not r["octet_stream"]]
            lo_ok = max(oks) if oks else int(args.lo * MiB)
            # 阶段 2：二分（先按 1 MiB 粒度快速收敛，再细化到 1 KiB）
            if args.skip_bisect:
                max_ok, min_fail = lo_ok, first_fail
            else:
                max_ok, min_fail = probe.bisect(lo_ok, first_fail, granularity=MiB // 1024)

        # ---- 结果 ----
        print("\n" + "=" * 60)
        print("结论：e2b SDK files.write 上传上限探针结果")
        print("=" * 60)
        print(f"  最大成功：{pretty(max_ok)}")
        print(f"  最小失败：{pretty(min_fail)}")
        if max_ok and min_fail:
            print(f"  阈值区间：({pretty(max_ok)}, {pretty(min_fail)}]")
            print(f"  估算上限 ≈ {min_fail / MiB:.3f} MiB（首次失败的请求体大小）")
        fail_rec = next((r for r in probe.results if not r["ok"]), None)
        if fail_rec:
            print(f"\n  首个失败请求：{fail_rec['mib']} MiB, HTTP={fail_rec['status_code']}, "
                  f"{fail_rec['error_type']}")
            print(f"  错误报文：{fail_rec['error']}")
        print("=" * 60)

    finally:
        if sbx is not None:
            E2B.kill(sbx)
    return 0


if __name__ == "__main__":
    sys.exit(main())
