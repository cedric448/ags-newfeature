#!/usr/bin/env python3
"""TC-10-5 已存在的工具能否直接更新系统盘容量。

实测结论（2026-11-07，ap-beijing，2C4Gi，账号上限 150Gi）：
  - UpdateSandboxTool 可更新 CustomConfiguration.Resources.Storage，无需重建工具
  - 更新是异步的：调用立即返回，工具回查约 3~30 秒后才变为新值
  - 扩容（20Gi -> 50Gi）与缩容（50Gi -> 20Gi）均被接受，无任何拦截
  - 已运行实例不受影响，保持创建时的旧容量
  - 更新后新建实例按新容量真实分配（df 实测为证）

踩坑：
  - 更新后立即回查会读到旧值，必须轮询到新值再继续，否则结论完全相反
  - 实例必须严格串行创建/停止，复用 ID 会读到上一个实例的容量

用法：
    python3 scripts/tc10_5_update_disk.py
    python3 scripts/tc10_5_update_disk.py --keep
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib import CFG, AgsApi, CleanupRegistry, ensure_domain  # noqa: E402

ENVD_CMD = "/usr/bin/envd -port 49983"
CPU, MEM = "2000m", "4096Mi"


def build_tool(name, storage):
    return {
        "ToolName": name,
        "ToolType": "custom",
        "RoleArn": CFG.role_arn,
        "NetworkConfiguration": {"NetworkMode": "SANDBOX"},
        "DefaultTimeout": "1h",
        "CustomConfiguration": {
            "Image": CFG.image,
            "ImageRegistryType": CFG.image_registry_type,
            "Command": ["sh"],
            "Args": ["-c", ENVD_CMD],
            "Ports": [{"Name": "envd", "Port": 49983, "Protocol": "TCP"}],
            "Probe": {
                "HttpGet": {"Path": "/health", "Port": 49983, "Scheme": "HTTP"},
                "ReadyTimeoutMs": 30000, "ProbeTimeoutMs": 2000, "ProbePeriodMs": 500,
                "SuccessThreshold": 1, "FailureThreshold": 100,
            },
            "Resources": {"CPU": CPU, "Memory": MEM, "Storage": storage},
        },
    }


def tool_storage(ags, tool_id):
    t = ags.get_tool(tool_id) or {}
    return ((t.get("CustomConfiguration") or {}).get("Resources") or {}).get("Storage")


def update_storage(ags, tool_id, storage, timeout=180):
    """发起更新并轮询等待生效（更新异步，必须等回查值真正变化）。"""
    t0 = time.time()
    ags.call("UpdateSandboxTool", {"ToolId": tool_id, "CustomConfiguration": {
        "Resources": {"CPU": CPU, "Memory": MEM, "Storage": storage}}})
    want = {storage, str(int(storage[:-2]) * 1024) + "Mi"}
    cur = None
    while time.time() - t0 < timeout:
        cur = tool_storage(ags, tool_id)
        if cur in want:
            return cur, round(time.time() - t0, 1)
        time.sleep(3)
    return cur, round(time.time() - t0, 1)


def measure(ags, cleanup, tool_id, label):
    """起全新实例、量根分区、同步等待停止完成。"""
    r = ags.call("StartSandboxInstance", {"ToolId": tool_id, "Timeout": "20m"})
    iid = (r.get("Instance") or {}).get("InstanceId") or r.get("InstanceId")
    cleanup.instance(ags, iid)
    ags.wait_instance(iid, want="RUNNING", timeout=900)

    inst = ags.get_instance(iid) or {}
    echo = ((inst.get("CustomConfiguration") or {}).get("Resources") or {}).get("Storage")

    from e2b import Sandbox  # noqa: PLC0415
    gib = None
    try:
        out = Sandbox.connect(iid).commands.run(
            "df -B1 / | tail -1 | awk '{print $2}'", user="root", timeout=60).stdout.strip()
        gib = round(int(out) / 1024.0 ** 3, 2)
    except Exception:  # noqa: BLE001
        pass

    print("  %-20s 工具=%-7s 实例回显=%-8s df=%sGiB" % (
        label, tool_storage(ags, tool_id), echo, gib))
    sys.stdout.flush()

    try:
        ags.stop_instance(iid)
        ags.wait_instance_gone(iid, timeout=300)
    except Exception:  # noqa: BLE001
        pass
    time.sleep(5)
    return {"label": label, "instance_id": iid, "echo": echo, "df_gib": gib}


def near(a, b, tol=0.08):
    return a is not None and abs(a - b) / float(b) <= tol


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep", action="store_true")
    args = ap.parse_args()

    ensure_domain()
    ags = AgsApi()
    cleanup = CleanupRegistry(keep=args.keep or CFG.keep_resources)
    name = "%s-upddisk-%d" % (CFG.run_prefix, int(time.time()))

    print("=== TC-10-5 已存在工具更新系统盘容量 ===")
    tool_id = ags.create_tool(build_tool(name, "20Gi"))["ToolId"]
    cleanup.tool(ags, tool_id)
    ags.wait_tool(tool_id, want="ACTIVE", timeout=900)
    print("[1] 创建工具 %s，声明 20Gi" % tool_id)

    steps = [measure(ags, cleanup, tool_id, "t0 初始(20Gi)")]

    print("[2] UpdateSandboxTool -> 50Gi（扩容）")
    echo1, w1 = update_storage(ags, tool_id, "50Gi")
    print("    工具回查 = %s（耗时 %ss）" % (echo1, w1))
    steps.append(measure(ags, cleanup, tool_id, "t1 扩容后(50Gi)"))

    print("[3] UpdateSandboxTool -> 20Gi（缩容）")
    echo2, w2 = update_storage(ags, tool_id, "20Gi")
    print("    工具回查 = %s（耗时 %ss）" % (echo2, w2))
    steps.append(measure(ags, cleanup, tool_id, "t2 缩容后(20Gi)"))

    t0, t1, t2 = steps
    checks = [
        ("工具可直接更新容量（无需重建）", echo1 == "50Gi" and echo2 == "20Gi"),
        ("初始实例为 20Gi", near(t0["df_gib"], 20)),
        ("扩容后新实例为 50Gi", near(t1["df_gib"], 50)),
        ("缩容后新实例为 20Gi", near(t2["df_gib"], 20)),
        ("更新后容量真实分配（非仅回显）", near(t1["df_gib"], 50) and near(t2["df_gib"], 20)),
    ]

    print("")
    print("=" * 62)
    print("结论汇总")
    print("=" * 62)
    for name_, ok in checks:
        print("  %-32s %s" % (name_, "PASS" if ok else "FAIL"))
    passed = sum(1 for _, ok in checks if ok)
    print("-" * 62)
    print("  %d/%d 通过" % (passed, len(checks)))
    print("=" * 62)

    result = {"tool_id": tool_id, "steps": steps,
              "update_wait_expand_s": w1, "update_wait_shrink_s": w2,
              "checks": [{"name": n, "pass": ok} for n, ok in checks],
              "summary": {"pass": passed, "total": len(checks)}}
    p = Path("reports/artifacts/tc10-5-update-disk.json")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print("")
    print("明细已写入 %s" % p)
    return 0 if passed == len(checks) else 1


if __name__ == "__main__":
    sys.exit(main())
