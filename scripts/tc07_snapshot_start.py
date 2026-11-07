#!/usr/bin/env python3
"""TC-07 快照创建实例的真实加速验证。

完整链路：
  1. 创建 custom 工具（SANDBOX 模式）
  2. 用 AgentCBS 系统盘起一个源实例（快照的前置条件）
  3. CreateSandboxSnapshot 打快照
  4. 对照测量：冷启动 vs 从 SnapshotId 启动

关键结论（2026-11-06，ap-beijing，2C4Gi）：
  ProbePeriodMs=500 时，冷启动 ~1.95s，快照启动 ~4.46s —— 快照反而慢 2.3 倍。
  原因：本镜像冷启动极快（已预热），而快照恢复有固定开销（~4.5s）。

踩坑记录：
  - 快照必须用 AgentCBS 系统盘实例：Metadata x-ags-agent-cbs-system-disk=true
  - 从快照启动只能传 SnapshotId，不能再传 ToolId（否则 InvalidParameter）
  - 健康探测周期严重影响测量：ProbePeriodMs=2000 时冷启动 3.3s，500 时 1.9s

用法：
    python3 scripts/tc07_snapshot_start.py
    python3 scripts/tc07_snapshot_start.py --probe-ms 500 --rounds 5 --concurrency 10
    python3 scripts/tc07_snapshot_start.py --keep
"""
from __future__ import annotations

import argparse
import json
import statistics as st
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib import CFG, AgsApi, CleanupRegistry  # noqa: E402

ENVD_CMD = "/usr/bin/envd -port 49983"
CBS_SYSTEM_DISK = "x-ags-agent-cbs-system-disk"


def build_payload(name: str, probe_ms: int) -> dict:
    return {
        "ToolName": name,
        "ToolType": "custom",
        "Description": "TC-07 snapshot start",
        "NetworkConfiguration": {"NetworkMode": "SANDBOX"},
        "DefaultTimeout": "1h",
        "RoleArn": CFG.role_arn,
        "CustomConfiguration": {
            "Image": CFG.image,
            "ImageRegistryType": CFG.image_registry_type,
            "Command": ["sh"],
            "Args": ["-c", ENVD_CMD],
            "Ports": [{"Name": "envd", "Port": 49983, "Protocol": "TCP"}],
            "Resources": {"CPU": "2000m", "Memory": "4096Mi"},
            "Probe": {
                "HttpGet": {"Path": "/health", "Port": 49983, "Scheme": "HTTP"},
                "ReadyTimeoutMs": 30000,
                "ProbeTimeoutMs": 2000,
                "ProbePeriodMs": probe_ms,
                "SuccessThreshold": 1,
                "FailureThreshold": 100,
            },
        },
    }


def start_and_wait(ags: AgsApi, payload: dict) -> tuple[float, str]:
    """发起启动并轮询到 RUNNING，返回 (耗时秒, 实例ID)。"""
    t0 = time.time()
    resp = ags.call("StartSandboxInstance", payload)
    iid = (resp.get("Instance") or {}).get("InstanceId") or resp.get("InstanceId")
    ags.wait_instance(iid, want="RUNNING", timeout=900)
    return round(time.time() - t0, 3), iid


def measure_serial(ags: AgsApi, label: str, payload: dict, rounds: int) -> dict:
    vals = []
    for i in range(rounds):
        try:
            dt, iid = start_and_wait(ags, payload)
            vals.append(dt)
            print(f"  {label} r{i + 1}: {dt}s", flush=True)
            ags.stop_instance(iid)
            ags.wait_instance_gone(iid, timeout=180)
        except Exception as exc:  # noqa: BLE001
            print(f"  {label} r{i + 1}: ERR {str(exc)[:120]}", flush=True)
        time.sleep(2)
    if not vals:
        return {"vals": [], "median": None, "avg": None}
    return {"vals": vals, "median": round(st.median(vals), 3), "avg": round(st.mean(vals), 3)}


def measure_concurrent(ags: AgsApi, payload: dict, n: int) -> dict:
    durs: list[float] = []
    lock = threading.Lock()

    def one(_i: int) -> None:
        try:
            dt, iid = start_and_wait(ags, payload)
            with lock:
                durs.append(dt)
            ags.stop_instance(iid)
        except Exception as exc:  # noqa: BLE001
            print(f"    conc err: {str(exc)[:100]}", flush=True)

    t0 = time.time()
    threads = [threading.Thread(target=one, args=(i,)) for i in range(n)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    wall = time.time() - t0
    return {
        "n": n,
        "wall_s": round(wall, 2),
        "ok": len(durs),
        "avg_s": round(st.mean(durs), 3) if durs else None,
        "max_s": round(max(durs), 3) if durs else None,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe-ms", type=int, default=500,
                    help="健康探测周期（关键！默认 2000 会掩盖真实差异）")
    ap.add_argument("--rounds", type=int, default=5, help="串行轮次")
    ap.add_argument("--concurrency", type=int, default=10, help="并发路数")
    ap.add_argument("--keep", action="store_true", help="保留资源")
    args = ap.parse_args()

    ags = AgsApi()
    cleanup = CleanupRegistry(keep=args.keep or CFG.keep_resources)
    ts = int(time.time())
    name = f"{CFG.run_prefix}-tc07-{ts}"

    print("=== TC-07 快照启动加速验证 ===")
    print(f"region={ags.region} image={CFG.image} probe={args.probe_ms}ms")

    # 1) 工具
    tool_id = ags.create_tool(build_payload(name, args.probe_ms))["ToolId"]
    cleanup.tool(ags, tool_id)
    ags.wait_tool(tool_id, want="ACTIVE", timeout=900)
    print(f"[1] 工具 ACTIVE {tool_id}", flush=True)

    # 2) 源实例（必须 AgentCBS 系统盘）
    print("[2] 起源实例（AgentCBS 系统盘）...", flush=True)
    resp = ags.call("StartSandboxInstance", {
        "ToolId": tool_id, "Timeout": "1h",
        "Metadata": [{"Name": CBS_SYSTEM_DISK, "Value": "true"}],
    })
    src = (resp.get("Instance") or {}).get("InstanceId") or resp.get("InstanceId")
    cleanup.instance(ags, src)
    ags.wait_instance(src, want="RUNNING", timeout=900)
    print(f"    源实例 RUNNING {src}", flush=True)

    # 3) 快照
    print("[3] 创建快照...", flush=True)
    t0 = time.time()
    snap = ags.call("CreateSandboxSnapshot", {
        "InstanceId": src,
        "SnapshotName": f"{CFG.run_prefix}-snap-{ts}",
        "Memory": False,
    }).get("Snapshot") or {}
    snap_id = snap.get("SnapshotId")
    print(f"    快照 {snap_id} status={snap.get('Status')} 耗时={time.time() - t0:.2f}s", flush=True)
    if not snap_id:
        print("!! 快照创建失败，无法继续对照")
        return 1

    # 4) 对照
    print(f"\n[4] 冷启动（{args.rounds} 轮）", flush=True)
    cold = measure_serial(ags, "cold", {"ToolId": tool_id, "Timeout": "10m"}, args.rounds)

    print(f"\n[5] 快照启动（{args.rounds} 轮，仅 SnapshotId）", flush=True)
    snap_res = measure_serial(ags, "snap", {"SnapshotId": snap_id, "Timeout": "10m"}, args.rounds)

    print(f"\n[6] 并发 {args.concurrency} 路", flush=True)
    print("  快照并发恢复:", flush=True)
    snap_conc = measure_concurrent(ags, {"SnapshotId": snap_id, "Timeout": "10m"}, args.concurrency)
    time.sleep(5)
    print("  冷启动并发:", flush=True)
    cold_conc = measure_concurrent(ags, {"ToolId": tool_id, "Timeout": "10m"}, args.concurrency)

    # 汇总
    print()
    print("=" * 62)
    print(f"结论汇总（ProbePeriodMs={args.probe_ms}，单位秒）")
    print("=" * 62)
    print(f"{'场景':<20}{'冷启动':>12}{'快照启动':>14}{'差异':>10}")
    print("-" * 62)
    c_med, s_med = cold["median"], snap_res["median"]
    pct = "" if not c_med or not s_med else f"{(s_med - c_med) / c_med * 100:+.1f}%"
    print(f"{'串行中位数':<18}{c_med:>12}{s_med:>14}{pct:>10}")
    print(f"{'并发批次墙钟':<16}{cold_conc['wall_s']:>12}{snap_conc['wall_s']:>14}")
    print("=" * 62)
    if c_med and s_med:
        verdict = "快照更慢" if s_med > c_med else "快照更快"
        print(f"判定：{verdict}（{pct}）")

    out = {
        "params": {"probe_ms": args.probe_ms, "rounds": args.rounds,
                   "concurrency": args.concurrency},
        "snapshot": {"id": snap_id, "status": snap.get("Status")},
        "cold": cold, "snapshot_start": snap_res,
        "cold_concurrent": cold_conc, "snapshot_concurrent": snap_conc,
    }
    path = Path("reports/artifacts/tc07-snapshot-start.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n明细已写入 {path}")

    # 清理快照
    if not args.keep:
        try:
            ags.call("DeleteSandboxSnapshot", {"SnapshotId": snap_id})
            print(f"[cleanup] 快照 {snap_id} 已删除")
        except Exception as exc:  # noqa: BLE001
            print(f"[cleanup] 删除快照失败: {str(exc)[:120]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
