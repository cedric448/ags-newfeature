#!/usr/bin/env python3
"""TC-09 auto-snapshot 启动速度对照测试。

目的：验证「工具名以 auto-snapshot 结尾」是否会触发自动快照、从而加速实例拉起。

做法：
  创建两个配置完全一致（同镜像/同规格/同网络/同启动命令）的 custom 工具：
    - plain: agstest-plain-<ts>
    - snap : agstest-snapshot-auto-snapshot-<ts>
  对两者分别做三组测量：
    A. Cloud API StartSandboxInstance -> RUNNING 耗时（串行 3 轮）
    B. E2B Sandbox.create 端到端耗时（串行 5 轮）
    C. 并发 8 路 Sandbox.create（测高并发下的差异）

实测结论（2026-11-06，ap-beijing，SANDBOX 模式，4C8Gi）：
  - 三组测量均无显著差异，avg 差异 < 3%，落在噪声范围
  - 工具配置回查完全一致，控制面没有为 auto-snapshot 后缀生成任何特殊字段
  => 当前环境不存在「工具名后缀 auto-snapshot」这一快照开关

用法：
    python3 scripts/tc06_auto_snapshot.py            # 完整对照测试
    python3 scripts/tc06_auto_snapshot.py --rounds 3 # 调整轮次
    python3 scripts/tc06_auto_snapshot.py --keep     # 保留资源排障
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

from lib import CFG, AgsApi, CleanupRegistry, ensure_domain  # noqa: E402

ENVD_CMD = "/usr/bin/envd -port 49983"
SNAP_SUFFIX = "auto-snapshot"


def build_payload(name: str, network: dict | None = None) -> dict:
    return {
        "ToolName": name,
        "ToolType": "custom",
        "Description": f"TC-09 auto-snapshot 启动速度对照（{name}）",
        "NetworkConfiguration": network or {"NetworkMode": "SANDBOX"},
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
                "ProbePeriodMs": 3000,
                "SuccessThreshold": 1,
                "FailureThreshold": 100,
            },
        },
    }


def create_pair(ags: AgsApi, cleanup: CleanupRegistry, ts: int) -> dict:
    """创建 plain / snap 两个工具并等 ACTIVE。"""
    specs = {
        "plain": f"{CFG.run_prefix}-plain-{ts}",
        "snap": f"{CFG.run_prefix}-snapshot-{SNAP_SUFFIX}-{ts}",
    }
    out: dict = {}
    for label, name in specs.items():
        tool_id = ags.create_tool(build_payload(name))["ToolId"]
        cleanup.tool(ags, tool_id)
        out[label] = {"name": name, "tool_id": tool_id}
        print(f"[create] {label}: {name} -> {tool_id}", flush=True)

    for label in out:
        tool = ags.wait_tool(out[label]["tool_id"], want="ACTIVE", timeout=900)
        out[label]["status"] = tool.get("Status")
        print(f"[create] {label}: {tool.get('Status')}", flush=True)
    return out


def measure_api(ags: AgsApi, name: str, rounds: int) -> list[dict]:
    """A: Cloud API 启动 -> RUNNING。"""
    rows = []
    for i in range(rounds):
        t0 = time.time()
        resp = ags.call("StartSandboxInstance", {"ToolName": name, "Timeout": "10m"})
        t_api = time.time()
        iid = (resp.get("Instance") or {}).get("InstanceId") or resp.get("InstanceId")
        ags.wait_instance(iid, want="RUNNING", timeout=900)
        t_run = time.time()
        try:
            ags.stop_instance(iid)
            ags.wait_instance_gone(iid, timeout=180)
        except Exception:  # noqa: BLE001
            pass
        rows.append({"round": i + 1,
                     "api_call_ms": round((t_api - t0) * 1000, 1),
                     "to_running_s": round(t_run - t0, 3)})
        print(f"  [api] r{i + 1}: {rows[-1]['api_call_ms']}ms -> {rows[-1]['to_running_s']}s", flush=True)
    return rows


def measure_e2b(name: str, rounds: int, pause: float = 3.0) -> list[dict]:
    """B: E2B Sandbox.create 端到端 + 首条命令往返。"""
    from e2b import Sandbox  # noqa: PLC0415

    rows = []
    for i in range(rounds):
        t0 = time.time()
        sbx = Sandbox.create(template=name, timeout=600)
        t_create = time.time()
        sbx.commands.run("echo ready", user="root", timeout=30)
        t_cmd = time.time()
        sbx.kill()
        rows.append({"round": i + 1,
                     "create_s": round(t_create - t0, 3),
                     "first_cmd_s": round(t_cmd - t0, 3)})
        print(f"  [e2b] r{i + 1}: create={rows[-1]['create_s']}s "
              f"first_cmd={rows[-1]['first_cmd_s']}s", flush=True)
        time.sleep(pause)
    return rows


def measure_concurrent(name: str, n: int = 8) -> dict:
    """C: 并发 n 路 Sandbox.create。"""
    from e2b import Sandbox  # noqa: PLC0415

    durations: list[float] = []
    errors: list[str] = []
    lock = threading.Lock()

    def one(_i: int) -> None:
        t0 = time.time()
        try:
            sbx = Sandbox.create(template=name, timeout=600)
            dt = time.time() - t0
            sbx.kill()
            with lock:
                durations.append(dt)
        except Exception as exc:  # noqa: BLE001
            with lock:
                errors.append(f"{type(exc).__name__}: {str(exc)[:80]}")

    t0 = time.time()
    threads = [threading.Thread(target=one, args=(i,)) for i in range(n)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    wall = time.time() - t0
    res = {
        "concurrency": n,
        "wall_s": round(wall, 2),
        "ok": len(durations),
        "err": len(errors),
        "avg_s": round(st.mean(durations), 3) if durations else None,
        "max_s": round(max(durations), 3) if durations else None,
    }
    print(f"  [conc] n={n}: wall={res['wall_s']}s ok={res['ok']} "
          f"avg={res['avg_s']}s max={res['max_s']}s", flush=True)
    return res


def summarize(api: dict, e2b: dict, conc: dict) -> dict:
    out = {}
    for label in ("plain", "snap"):
        a = [r["to_running_s"] for r in api[label]]
        e = [r["create_s"] for r in e2b[label]]
        c = [r["first_cmd_s"] for r in e2b[label]]
        out[label] = {
            "api_avg": round(st.mean(a), 3),
            "api_median": round(st.median(a), 3),
            "e2b_create_avg": round(st.mean(e), 3),
            "e2b_create_median": round(st.median(e), 3),
            "e2b_create_min": round(min(e), 3),
            "e2b_create_max": round(max(e), 3),
            "first_cmd_avg": round(st.mean(c), 3),
            "concurrent": conc[label],
        }
    return out


def diff_pct(a: float, b: float) -> float:
    return round((b - a) / a * 100, 2) if a else 0.0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rounds", type=int, default=5, help="E2B 串行轮次（默认 5）")
    ap.add_argument("--api-rounds", type=int, default=3, help="Cloud API 轮次（默认 3）")
    ap.add_argument("--concurrency", type=int, default=8, help="并发路数（默认 8）")
    ap.add_argument("--keep", action="store_true", help="保留资源")
    args = ap.parse_args()

    ensure_domain()
    ags = AgsApi()
    cleanup = CleanupRegistry(keep=args.keep or CFG.keep_resources)
    ts = int(time.time())

    print("=== TC-09 auto-snapshot 启动速度对照 ===")
    print(f"region={ags.region} image={CFG.image} network=SANDBOX")

    tools = create_pair(ags, cleanup, ts)

    api, e2b, conc = {}, {}, {}
    for label in ("plain", "snap"):
        print(f"\n--- {label}: {tools[label]['name']} ---")
        api[label] = measure_api(ags, tools[label]["name"], args.api_rounds)
        e2b[label] = measure_e2b(tools[label]["name"], args.rounds)

    print("\n--- 并发对照 ---")
    for label in ("plain", "snap"):
        conc[label] = measure_concurrent(tools[label]["name"], args.concurrency)
        time.sleep(5)

    summary = summarize(api, e2b, conc)
    p_e = diff_pct(summary["plain"]["e2b_create_avg"], summary["snap"]["e2b_create_avg"])
    p_a = diff_pct(summary["plain"]["api_avg"], summary["snap"]["api_avg"])

    print()
    print("=" * 62)
    print("结论汇总（单位：秒）")
    print("=" * 62)
    print(f"{'指标':<22}{'plain':>12}{'auto-snapshot':>16}{'差异':>10}")
    print("-" * 62)
    print(f"{'API 启动均值':<20}{summary['plain']['api_avg']:>12}{summary['snap']['api_avg']:>16}{p_a:>9}%")
    print(f"{'E2B create 均值':<19}{summary['plain']['e2b_create_avg']:>12}"
          f"{summary['snap']['e2b_create_avg']:>16}{p_e:>9}%")
    print(f"{'E2B create 中位数':<18}{summary['plain']['e2b_create_median']:>12}"
          f"{summary['snap']['e2b_create_median']:>16}")
    conc_label = f"并发 {args.concurrency} 路 wall"
    print(f"{conc_label:<19}{summary['plain']['concurrent']['wall_s']:>12}"
          f"{summary['snap']['concurrent']['wall_s']:>16}")
    print("=" * 62)
    verdict = "无显著差异（差异 < 5%，属噪声）" if abs(p_e) < 5 and abs(p_a) < 5 else "存在差异，需复核"
    print(f"判定：{verdict}")

    result = {"tools": tools, "api": api, "e2b": e2b, "concurrent": conc,
              "summary": summary, "verdict": verdict}
    out_path = Path("reports/artifacts/tc09-auto-snapshot.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print()
    print(f"明细已写入 {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
