#!/usr/bin/env python3
"""精确定位 AGS 数据面单文件上传上限（在已知区间内按候选值测试）。

已知：128 MiB 成功、256 MiB 被 stgw 以 413 拒绝。
本脚本在两者之间按候选值逐点测试，命中即停，避免二分带来的大量大文件传输。
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib import CFG, AgsApi, CleanupRegistry, E2B  # noqa: E402

ENVD_CMD = "/usr/bin/envd -port 49983"
MiB = 1024 * 1024
MiB_CANDIDATES = [255, 256, 254, 250, 240, 224]


def build_tool_payload(name, image, network):
    return {
        "ToolName": name, "ToolType": "custom", "Description": "AGS 上传上限精确探针",
        "NetworkConfiguration": network, "DefaultTimeout": "30m", "RoleArn": CFG.role_arn,
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


def try_upload(sbx, nbytes: int) -> dict:
    path = f"/tmp/u/{nbytes}.bin"
    t0 = time.time()
    rec = {"mib": round(nbytes / MiB, 3), "bytes": nbytes, "ok": False, "err": None, "sec": None}
    try:
        sbx.files.write(path, b"\x00" * nbytes, user="root", request_timeout=900)
        rec["ok"] = True
    except Exception as exc:  # noqa: BLE001
        rec["err"] = str(exc)[:200]
    rec["sec"] = round(time.time() - t0, 1)
    if rec["ok"]:
        try:
            E2B.run(sbx, f"rm -f {path}", user="root", timeout=60)
        except Exception:  # noqa: BLE001 - 清理失败不影响判定
            pass
    return rec


def main() -> int:
    ags = AgsApi()
    cleanup = CleanupRegistry(keep=CFG.keep_resources)
    tool_name = f"{CFG.run_prefix}-edge-{int(time.time())}"
    print(f"创建工具 {tool_name} ...")
    resp = ags.create_tool(build_tool_payload(tool_name, CFG.image, CFG.vpc_network()))
    tool_id = resp.get("ToolId")
    cleanup.tool(ags, tool_id)
    ags.wait_tool(tool_id, want="ACTIVE", timeout=600)
    print("工具 ACTIVE")

    resp = ags.start_instance({"ToolName": tool_name, "Timeout": "30m"})
    iid = (resp.get("Instance") or {}).get("InstanceId") or resp.get("InstanceId")
    cleanup.instance(ags, iid)
    ags.wait_instance(iid, want="RUNNING", timeout=900)
    print(f"实例 RUNNING {iid}")

    sbx = E2B.create(tool_name, timeout=1800)
    cleanup.sandbox(sbx)
    print(f"E2B 连接 {sbx.sandbox_id}")

    last_ok, first_fail, rows = None, None, []
    for mib in MiB_CANDIDATES:
        rec = try_upload(sbx, int(mib * MiB))
        rows.append(rec)
        mark = "OK " if rec["ok"] else "413"
        tail = "落盘成功" if rec["ok"] else rec["err"].splitlines()[0][:80] if rec["err"] else ""
        print(f"  [{mark}] {mib:>4} MiB  {rec['sec']:>6.1f}s  {tail}", flush=True)
        if rec["ok"]:
            last_ok = mib
        else:
            first_fail = mib
            if last_ok is not None:
                break  # 已夹住边界

    print("\n===== 精确结果 =====")
    print(f"最大成功: {last_ok} MiB  首个失败: {first_fail} MiB")
    if last_ok and first_fail:
        print(f"实际上传上限落在 ({last_ok} MiB, {first_fail} MiB]")
    E2B.kill(sbx)
    return 0


if __name__ == "__main__":
    sys.exit(main())
