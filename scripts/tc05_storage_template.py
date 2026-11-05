#!/usr/bin/env python3
"""AGS 存储模板（VolumeTemplate）挂载与读写性能测试。

三块存储模板：
  volt-q4t7c0ei  cedricbwang-cbs  AgentCbs  ReadWriteOnce
  volt-o8i4iftw  cedricbwang-cfs  Cfs       ReadWriteMany
  volt-4fhc8td8  cedricbwang-cos  Cos       ReadWriteMany

注意（实测结论）：
- CFS/COS 可正常挂载；
- AgentCBS 当前不可用：启动实例报 "AgentCBS Volume requires an AgentCBS SystemDisk instance"，
  且当前 API 无系统盘类型字段（产品尚未支持，见 reports/STORAGE-TEMPLATE-BENCH.md）。
- CFS 模板 PathPattern 为 /cedricbwang/${reuse_key}，目录必须预先存在。

用法：
    python3 scripts/tc05_storage_template.py               # CFS+COS 单机基准
    python3 scripts/tc05_storage_template.py --multi       # 双实例并发基准
    python3 scripts/tc05_storage_template.py --with-cbs    # 尝试 CBS（预期失败，用于复现）
    python3 scripts/tc05_storage_template.py --keep        # 保留资源排障
"""
from __future__ import annotations

import argparse
import json
import threading
import time
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib import CFG, AgsApi, CleanupRegistry, E2B, ensure_domain  # noqa: E402

IMAGE = CFG.image
ENVD_CMD = "/usr/bin/envd -port 49983"
VT_CFS = "cedricbwang-cfs"
VT_COS = "cedricbwang-cos"
VT_CBS = "cedricbwang-cbs"

BENCH_SEQ = r"""/bin/bash
for d in /mnt/vt-cfs /mnt/vt-cos; do
  echo "=== $d seq 256MiB ==="
  dd if=/dev/zero of=$d/bench.bin bs=1M count=256 conv=fdatasync 2>&1 | tail -1
  sync
  dd if=$d/bench.bin of=/dev/null bs=1M 2>&1 | tail -1
  rm -f $d/bench.bin
done
"""

BENCH_SMALL = r"""/bin/bash
for d in /mnt/vt-cfs /mnt/vt-cos; do
  echo "=== $d 4K x 2000 ==="
  s=$(date +%s%N)
  for i in $(seq 1 2000); do dd if=/dev/zero of=$d/s$i.bin bs=4k count=1 2>/dev/null; done
  e=$(date +%s%N); echo "write_ms=$(( (e-s)/1000000 ))"
  s=$(date +%s%N); cat $d/s*.bin > /dev/null; e=$(date +%s%N)
  echo "read_ms=$(( (e-s)/1000000 ))"
  rm -f $d/s*.bin
done
"""


def build_payload(name: str, with_cbs: bool) -> dict:
    mounts = [
        {"Name": "vt-cfs", "MountPath": "/mnt/vt-cfs",
         "VolumeTemplate": {"VolumeTemplateName": VT_CFS, "ReuseKey": "bench"}},
        {"Name": "vt-cos", "MountPath": "/mnt/vt-cos",
         "VolumeTemplate": {"VolumeTemplateName": VT_COS, "ReuseKey": "bench"}},
    ]
    if with_cbs:
        mounts.insert(0, {"Name": "vt-cbs", "MountPath": "/mnt/vt-cbs",
                          "VolumeTemplate": {"VolumeTemplateName": VT_CBS, "ReuseKey": "bench"}})
    return {
        "ToolName": name,
        "ToolType": "custom",
        "Description": "AGS 存储模板挂载与性能测试",
        "NetworkConfiguration": {"NetworkMode": "SANDBOX"},
        "DefaultTimeout": "1h",
        "RoleArn": CFG.role_arn,
        "StorageMounts": mounts,
        "CustomConfiguration": {
            "Image": IMAGE,
            "ImageRegistryType": CFG.image_registry_type,
            "Command": ["sh"], "Args": ["-c", ENVD_CMD],
            "Ports": [{"Name": "envd", "Port": 49983, "Protocol": "TCP"}],
            "Resources": {"CPU": "4000m", "Memory": "8192Mi"},
            "Probe": {"HttpGet": {"Path": "/health", "Port": 49983, "Scheme": "HTTP"},
                      "ReadyTimeoutMs": 30000, "ProbeTimeoutMs": 2000,
                      "ProbePeriodMs": 3000, "SuccessThreshold": 1, "FailureThreshold": 100},
        },
    }


def start_instance(ags: AgsApi, tool_name: str, timeout: str = "1h") -> str:
    resp = ags.call("StartSandboxInstance", {"ToolName": tool_name, "Timeout": timeout})
    iid = (resp.get("Instance") or {}).get("InstanceId") or resp.get("InstanceId")
    ags.wait_instance(iid, want="RUNNING", timeout=900)
    return iid


def run_bench(sbx, script: str, label: str) -> str:
    t0 = time.time()
    wrapper = "cat > /tmp/b.sh <<'AGSEOF'\n" + script + "\nAGSEOF\nbash /tmp/b.sh"
    res = E2B.run(sbx, wrapper, user="root", timeout=1800)
    code, out, err = res
    print(f"----- {label} (wall {time.time() - t0:.1f}s, exit={code}) -----")
    print(out)
    if err.strip():
        print("ERR", err[:300])
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--multi", action="store_true", help="双实例并发基准")
    ap.add_argument("--small", action="store_true", help="附加小文件基准")
    ap.add_argument("--with-cbs", action="store_true", help="尝试 CBS（预期启动失败）")
    ap.add_argument("--keep", action="store_true", help="保留资源")
    args = ap.parse_args()

    ensure_domain()
    ags = AgsApi()
    cleanup = CleanupRegistry(keep=args.keep or CFG.keep_resources)
    name = f"{CFG.run_prefix}-vt-{int(time.time())}"

    print(f"创建工具 {name} ...")
    tool_id = ags.create_tool(build_payload(name, args.with_cbs)).get("ToolId")
    cleanup.tool(ags, tool_id)
    tool = ags.wait_tool(tool_id, want="ACTIVE", timeout=900)
    print(f"工具 {tool.get('Status')}, ToolId={tool_id}")

    try:
        iid1 = start_instance(ags, name)
    except Exception as exc:  # noqa: BLE001
        print("启动实例失败:", str(exc)[:300])
        if args.with_cbs:
            print("\n>>> 预期结果：AgentCBS 当前不受支持（需要 AgentCBS 系统盘实例）")
        return 1
    cleanup.instance(ags, iid1)
    print(f"实例1 RUNNING {iid1}")

    from e2b import Sandbox
    sbx1 = Sandbox.create(template=name, timeout=7200)
    cleanup.sandbox(sbx1)
    print(f"sandbox1 {sbx1.sandbox_id}")

    if args.multi:
        iid2 = start_instance(ags, name)
        cleanup.instance(ags, iid2)
        sbx2 = Sandbox.create(template=name, timeout=7200)
        cleanup.sandbox(sbx2)
        print(f"实例2 RUNNING {iid2}, sandbox2 {sbx2.sandbox_id}")
        res = {}
        def job(tag, sbx):
            res[tag] = run_bench(sbx, BENCH_SEQ, tag)
        th = [threading.Thread(target=job, args=("M1", sbx1)),
              threading.Thread(target=job, args=("M2", sbx2))]
        [t.start() for t in th]
        [t.join() for t in th]
        # 共享可见性
        o1 = E2B.run(sbx1, "ls /mnt/vt-cfs /mnt/vt-cos", user="root", timeout=60)[1]
        o2 = E2B.run(sbx2, "ls /mnt/vt-cfs /mnt/vt-cos", user="root", timeout=60)[1]
        print("M1 sees:", o1)
        print("M2 sees:", o2)
    else:
        run_bench(sbx1, BENCH_SEQ, "single-256MiB")
        if args.small:
            run_bench(sbx1, BENCH_SMALL, "single-smallfile")
    return 0


if __name__ == "__main__":
    sys.exit(main())
