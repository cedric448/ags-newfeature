#!/usr/bin/env python3
"""TC-08 带内存快照与 Pause/Resume 延迟测试。

核心结论（2026-11-06，ap-beijing，2C4Gi，ProbePeriodMs=500）：
  - CreateSandboxSnapshot 不支持 Memory=true（报 "Memory=true is not supported for Runtime Snapshots"）
    => 想保留进程/内存状态，唯一可用路径是 Pause/Resume
  - Pause/Resume 带内存：pause ~8.4s，resume ~1.85s，进程 PID 不变（内存态真实保留）
  - Pause/Resume 不带内存：pause ~0.43s，resume ~1.96s
  - 磁盘快照（Memory=false）：创建 ~0.33s，恢复 ~1.97s，保留磁盘但不保留进程

前提：暂停/恢复需要在 AgentCBS 系统盘实例上（Metadata x-ags-agent-cbs-system-disk=true）。

用法：
    python3 scripts/tc08_pause_resume.py
    python3 scripts/tc08_pause_resume.py --rounds 5 --verify-memory
    python3 scripts/tc08_pause_resume.py --keep
"""
from __future__ import annotations

import argparse
import json
import statistics as st
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib import CFG, AgsApi, CleanupRegistry, ensure_domain  # noqa: E402

ENVD_CMD = "/usr/bin/envd -port 49983"
CBS_SYSTEM_DISK = "x-ags-agent-cbs-system-disk"


def build_payload(name: str, probe_ms: int = 500) -> dict:
    return {
        "ToolName": name,
        "ToolType": "custom",
        "Description": "TC-08 pause/resume",
        "NetworkConfiguration": {"NetworkMode": "SANDBOX"},
        "DefaultTimeout": "2h",
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


def wait_status(ags: AgsApi, iid: str, want: str, timeout: float = 600, interval: float = 0.2) -> float:
    t0 = time.time()
    while time.time() - t0 < timeout:
        info = ags.get_instance(iid)
        status = (info or {}).get("Status")
        if status == want:
            return round(time.time() - t0, 3)
        if status in ("PAUSE_FAILED", "RESUME_FAILED", "FAILED"):
            raise RuntimeError(f"实例进入 {status}: {((info or {}).get('StatusReason') or '')[:120]}")
        time.sleep(interval)
    raise TimeoutError(f"等待 {want} 超时，最后状态 {status}")


def new_instance(ags: AgsApi, tool_id: str) -> str:
    resp = ags.call("StartSandboxInstance", {
        "ToolId": tool_id, "Timeout": "2h",
        "Metadata": [{"Name": CBS_SYSTEM_DISK, "Value": "true"}],
    })
    iid = (resp.get("Instance") or {}).get("InstanceId") or resp.get("InstanceId")
    ags.wait_instance(iid, want="RUNNING", timeout=900)
    return iid


def measure_pr(ags: AgsApi, tool_id: str, memory: bool, rounds: int) -> dict:
    pauses, resumes = [], []
    for i in range(rounds):
        iid = new_instance(ags, tool_id)
        try:
            t0 = time.time()
            resp = ags.call("PauseSandboxInstance", {"InstanceId": iid, "Memory": memory})
            if resp.get("InstanceStatus") != "PAUSED":
                wait_status(ags, iid, "PAUSED")
            pauses.append(round(time.time() - t0, 3))

            t0 = time.time()
            ags.call("ResumeSandboxInstance", {"InstanceId": iid, "Timeout": "2h"})
            wait_status(ags, iid, "RUNNING")
            resumes.append(round(time.time() - t0, 3))
            print(f"  Memory={memory} r{i + 1}: pause={pauses[-1]}s resume={resumes[-1]}s", flush=True)
        finally:
            try:
                ags.stop_instance(iid)
            except Exception:  # noqa: BLE001
                pass
        time.sleep(2)
    return {
        "memory": memory, "pauses": pauses, "resumes": resumes,
        "pause_median": round(st.median(pauses), 3) if pauses else None,
        "resume_median": round(st.median(resumes), 3) if resumes else None,
    }


def verify_memory_kept(ags: AgsApi, tool_id: str) -> dict:
    """验证带内存 Resume 后进程未重启（PID 不变）。"""
    from e2b import Sandbox  # noqa: PLC0415

    iid = new_instance(ags, tool_id)
    try:
        token = f"mem-{int(time.time())}"
        sbx = Sandbox.connect(iid)
        sbx.commands.run(
            f"echo {token} > /tmp/m.txt; "
            f"nohup sh -c 'echo {token} > /tmp/p.txt; sleep 200000' >/dev/null 2>&1 & "
            "sleep 1; echo ok", user="root", timeout=60)
        time.sleep(2)
        before = sbx.commands.run(
            "cat /tmp/m.txt; echo ---; pgrep -af 'sleep 200000' | head -2; "
            "echo ---; cat /proc/uptime", user="root", timeout=60).stdout

        t0 = time.time()
        ags.call("PauseSandboxInstance", {"InstanceId": iid, "Memory": True})
        wait_status(ags, iid, "PAUSED")
        pause_s = round(time.time() - t0, 3)
        t0 = time.time()
        ags.call("ResumeSandboxInstance", {"InstanceId": iid, "Timeout": "2h"})
        wait_status(ags, iid, "RUNNING")
        resume_s = round(time.time() - t0, 3)

        after = Sandbox.connect(iid).commands.run(
            "cat /tmp/m.txt; echo ---; pgrep -af 'sleep 200000' | head -2; "
            "echo ---; cat /proc/uptime", user="root", timeout=60).stdout
        return {"pause_s": pause_s, "resume_s": resume_s,
                "before": before, "after": after, "token": token}
    finally:
        try:
            ags.stop_instance(iid)
        except Exception:  # noqa: BLE001
            pass


def probe_memory_snapshot_supported(ags: AgsApi, tool_id: str) -> dict:
    """验证 CreateSandboxSnapshot 是否支持 Memory=true。"""
    iid = new_instance(ags, tool_id)
    try:
        try:
            snap = ags.call("CreateSandboxSnapshot", {
                "InstanceId": iid, "SnapshotName": f"memtest-{int(time.time())}",
                "Memory": True,
            }).get("Snapshot") or {}
            sid = snap.get("SnapshotId")
            if sid:
                try:
                    ags.call("DeleteSandboxSnapshot", {"SnapshotId": sid})
                except Exception:  # noqa: BLE001
                    pass
            return {"supported": True, "detail": snap}
        except Exception as exc:  # noqa: BLE001
            return {"supported": False, "detail": str(exc)[:300]}
    finally:
        try:
            ags.stop_instance(iid)
        except Exception:  # noqa: BLE001
            pass


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rounds", type=int, default=3)
    ap.add_argument("--verify-memory", action="store_true", help="验证内存态是否保留")
    ap.add_argument("--probe-ms", type=int, default=500)
    ap.add_argument("--keep", action="store_true")
    args = ap.parse_args()

    ensure_domain()
    ags = AgsApi()
    cleanup = CleanupRegistry(keep=args.keep or CFG.keep_resources)
    ts = int(time.time())
    name = f"{CFG.run_prefix}-tc08-{ts}"

    print("=== TC-08 带内存快照与 Pause/Resume ===")
    tool_id = ags.create_tool(build_payload(name, args.probe_ms))["ToolId"]
    cleanup.tool(ags, tool_id)
    ags.wait_tool(tool_id, want="ACTIVE", timeout=900)
    print(f"工具 ACTIVE {tool_id}", flush=True)

    print("\n[1] 检查 CreateSandboxSnapshot 是否支持 Memory=true", flush=True)
    mem_snap = probe_memory_snapshot_supported(ags, tool_id)
    print(f"    supported={mem_snap['supported']}", flush=True)
    if not mem_snap["supported"]:
        print(f"    原因: {mem_snap['detail'][:160]}", flush=True)

    print(f"\n[2] Pause/Resume 带内存（{args.rounds} 轮）", flush=True)
    with_mem = measure_pr(ags, tool_id, True, args.rounds)
    print(f"    pause 中位数={with_mem['pause_median']}s  resume 中位数={with_mem['resume_median']}s")

    print(f"\n[3] Pause/Resume 不带内存（{args.rounds} 轮）", flush=True)
    no_mem = measure_pr(ags, tool_id, False, args.rounds)
    print(f"    pause 中位数={no_mem['pause_median']}s  resume 中位数={no_mem['resume_median']}s")

    verify = None
    if args.verify_memory:
        print("\n[4] 验证带内存 Resume 后进程是否保留", flush=True)
        verify = verify_memory_kept(ags, tool_id)
        print(f"    pause={verify['pause_s']}s resume={verify['resume_s']}s")
        print("    --- before ---"); print(verify["before"])
        print("    --- after  ---"); print(verify["after"])

    print()
    print("=" * 64)
    print(f"结论汇总（ProbePeriodMs={args.probe_ms}，单位秒）")
    print("=" * 64)
    print(f"{'模式':<24}{'pause':>12}{'resume':>12}")
    print("-" * 64)
    print(f"{'带内存 Memory=true':<20}{with_mem['pause_median']:>12}{with_mem['resume_median']:>12}")
    print(f"{'不带内存 Memory=false':<18}{no_mem['pause_median']:>12}{no_mem['resume_median']:>12}")
    print("=" * 64)
    print(f"带内存快照（Memory=true）: {'支持' if mem_snap['supported'] else '不支持'}")
    if verify:
        same = verify["before"].split("---")[1].split() == verify["after"].split("---")[1].split()
        print(f"内存态保留: {'是（PID 不变）' if same else '需人工核对'}")

    out = {"params": vars(args), "memory_snapshot": mem_snap,
           "with_memory": with_mem, "without_memory": no_mem, "verify": verify}
    path = Path("reports/artifacts/tc08-pause-resume.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n明细已写入 {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
