#!/usr/bin/env python3
"""BUG-02 复现：AGS 沙箱内 clock_gettime(CLOCK_MONOTONIC) 回退系统调用。

判据：若 glibc 调用耗时 ≈ 强制 syscall 耗时，说明 vDSO 快路径未生效。

实测基线（2026-11-07，ap-beijing）：
  AGS 沙箱   : via_glibc = 240 ns, via_syscall = 240 ns  <- 回退
  正常主机   : clock_gettime = 29 ns, syscall(getppid) = 59 ns

用法：
    python3 scripts/bug02_clock_vdso.py --tool custom-fredtest-2
    python3 scripts/bug02_clock_vdso.py --all
"""
from __future__ import annotations

import argparse
import base64
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib import CFG, AgsApi, CleanupRegistry, ensure_domain  # noqa: E402

PROBE_C = r"""
#define _GNU_SOURCE
#include <stdio.h>
#include <time.h>
#include <sys/syscall.h>
#include <unistd.h>
#include <stdlib.h>

static inline double ns(void) {
    struct timespec t; clock_gettime(CLOCK_MONOTONIC, &t);
    return t.tv_sec * 1e9 + t.tv_nsec;
}

int main(void) {
    long n = 20000; struct timespec ts; double a, b;

    a = ns(); for (long i = 0; i < n; i++) clock_gettime(CLOCK_MONOTONIC, &ts); b = ns();
    printf("via_glibc=%.1f\n", (b - a) / n);

    a = ns(); for (long i = 0; i < n; i++) clock_gettime(CLOCK_MONOTONIC_COARSE, &ts); b = ns();
    printf("coarse=%.1f\n", (b - a) / n);

    a = ns(); for (long i = 0; i < n; i++) syscall(SYS_clock_gettime, CLOCK_MONOTONIC, &ts); b = ns();
    printf("via_syscall=%.1f\n", (b - a) / n);

    a = ns(); for (long i = 0; i < n; i++) syscall(SYS_getppid); b = ns();
    printf("getppid=%.1f\n", (b - a) / n);
    return 0;
}
"""


def probe_host() -> dict:
    """采集沙箱内环境信息与 TSC 标记。"""
    return {
        "kernel": "uname -r",
        "clocksource": "cat /sys/devices/system/clocksource/clocksource0/current_clocksource",
        "available": "cat /sys/devices/system/clocksource/clocksource0/available_clocksource",
        "cpu_flags": ("grep -m1 ^flags /proc/cpuinfo | tr ' ' '\\n' | "
                      "grep -E '^(tsc|constant_tsc|nonstop_tsc|tsc_known_freq|rdtscp)$' | "
                      "tr '\\n' ' '"),
        "vdso": "grep vdso /proc/self/maps | head -1",
    }


def run_one(ags, cleanup, tool_name, use_type) -> dict:
    from e2b import Sandbox  # noqa: PLC0415

    rec = {"tool": tool_name}
    payload = {"Timeout": "15m"}
    if use_type == "name":
        payload["ToolName"] = tool_name
    else:
        payload["ToolId"] = tool_name
    try:
        r = ags.call("StartSandboxInstance", payload)
        iid = (r.get("Instance") or {}).get("InstanceId") or r.get("InstanceId")
        cleanup.instance(ags, iid)
        ags.wait_instance(iid, want="RUNNING", timeout=900)
    except Exception as exc:  # noqa: BLE001
        rec["error"] = str(exc)[:200]
        return rec

    rec["instance"] = iid
    sbx = Sandbox.connect(iid)
    for key, cmd in probe_host().items():
        try:
            rec[key] = sbx.commands.run(cmd, user="root", timeout=60).stdout.strip()
        except Exception:  # noqa: BLE001
            rec[key] = None

    b64 = base64.b64encode(PROBE_C.encode()).decode()
    sbx.commands.run(f"echo {b64} | base64 -d > /tmp/bug02.c", user="root", timeout=60)
    build = sbx.commands.run("gcc -O2 -o /tmp/bug02 /tmp/bug02.c 2>/dev/null && echo OK || echo NO_GCC",
                             user="root", timeout=300).stdout.strip()
    if "OK" not in build:
        rec["error"] = "镜像内无 gcc，无法编译探针"
        return rec

    out = sbx.commands.run("/tmp/bug02", user="root", timeout=180).stdout.strip()
    for line in out.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            try:
                rec[k.strip()] = float(v)
            except ValueError:
                pass

    g, s = rec.get("via_glibc"), rec.get("via_syscall")
    if g and s:
        ratio = g / s
        rec["glibc_over_syscall"] = round(ratio, 2)
        # 判据：比值 > 0.8 说明 glibc 没走 vDSO
        rec["vdso_effective"] = ratio < 0.8
        rec["verdict"] = "PASS (vDSO 生效)" if ratio < 0.8 else "FAIL (回退 syscall)"

    try:
        ags.stop_instance(iid)
        ags.wait_instance_gone(iid, timeout=300)
    except Exception:  # noqa: BLE001
        pass
    time.sleep(3)
    return rec


DEFAULT_TOOLS = [
    ("custom", "custom-fredtest-2"),
    ("custom", "evocodebench-coding"),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tool", help="单个 Tool 名称")
    ap.add_argument("--all", action="store_true", help="遍历默认 Tool 列表")
    ap.add_argument("--keep", action="store_true")
    args = ap.parse_args()

    ensure_domain()
    ags = AgsApi()
    cleanup = CleanupRegistry(keep=args.keep or CFG.keep_resources)

    if args.tool:
        targets = [("custom", args.tool)]
    else:
        targets = DEFAULT_TOOLS

    print("=== BUG-02 复现：clock_gettime vDSO 回退检测 ===")
    print("region=%s" % ags.region)
    print("")
    print("%-32s %10s %10s %10s %10s  %s" % (
        "Tool", "glibc", "coarse", "syscall", "getppid", "判定"))
    print("-" * 96)

    results = []
    for _ttype, name in targets:
        rec = run_one(ags, cleanup, name, "name")
        results.append(rec)
        if rec.get("error"):
            print("%-32s  ERROR: %s" % (name, rec["error"][:60]))
        else:
            print("%-32s %10.1f %10.1f %10.1f %10.1f  %s" % (
                name, rec.get("via_glibc", 0), rec.get("coarse", 0),
                rec.get("via_syscall", 0), rec.get("getppid", 0),
                rec.get("verdict", "?")))
            print("    kernel=%s clocksource=%s" % (rec.get("kernel"), rec.get("clocksource")))
            print("    tsc_flags=[%s]  ratio=%.2f" % (rec.get("cpu_flags"),
                                                       rec.get("glibc_over_syscall", 0)))
        sys.stdout.flush()

    ok = [r for r in results if r.get("verdict", "").startswith("PASS")]
    bad = [r for r in results if r.get("verdict", "").startswith("FAIL")]
    print("")
    print("=" * 96)
    print("汇总：%d 个 Tool 中，vDSO 生效 %d 个，回退 syscall %d 个" % (
        len(results), len(ok), len(bad)))
    if bad:
        print("判定：**BUG-02 复现** —— CLOCK_MONOTONIC 未走 vDSO 快路径")
    print("=" * 96)

    path = Path("reports/artifacts/bug02-clock-vdso.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print("")
    print("明细已写入 %s" % path)
    return 0 if bad else 1


if __name__ == "__main__":
    sys.exit(main())
