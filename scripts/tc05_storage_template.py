#!/usr/bin/env python3
"""AGS 存储模板（VolumeTemplate）挂载与读写性能测试。

三块存储模板：
  volt-q4t7c0ei  cedricbwang-cbs  AgentCbs  ReadWriteOnce
  volt-o8i4iftw  cedricbwang-cfs  Cfs       ReadWriteMany
  volt-4fhc8td8  cedricbwang-cos  Cos       ReadWriteMany

注意（实测结论）：
- CFS/COS 通过 VolumeTemplate 直接挂载；
- **AgentCBS 不能用 VolumeTemplate 挂**：它走独立的 Volume 资源，且实例必须开启
  AgentCBS 系统盘（Metadata: x-ags-agent-cbs-system-disk=true），否则报
  "AgentCBS Volume requires an AgentCBS SystemDisk instance"。
  正确做法见 scripts/tc05_cbs_volume.py。
- CFS 模板 PathPattern 为 /cedricbwang/${reuse_key}，目录必须预先存在。

用法：
    python3 scripts/tc05_storage_template.py               # CFS+COS 单机基准
    python3 scripts/tc05_storage_template.py --multi       # 双实例并发基准
    python3 scripts/tc05_storage_template.py --with-cbs    # 额外挂 CBS 数据卷（Volume + 系统盘开关）
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

BENCH_DIRS = "/mnt/vt-cfs /mnt/vt-cos"
BENCH_DIRS_CBS = "/workspace/data /mnt/vt-cfs /mnt/vt-cos"

BENCH_SEQ = r"""set +e
for d in __DIRS__; do
  echo "=== $d seq 256MiB ==="
  dd if=/dev/zero of=$d/bench.bin bs=1M count=256 conv=fdatasync 2>&1 | tail -1
  sync
  dd if=$d/bench.bin of=/dev/null bs=1M 2>&1 | tail -1
  rm -f $d/bench.bin
done
"""

BENCH_SMALL = r"""set +e
for d in __DIRS__; do
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
    # AgentCBS 不走 VolumeTemplate：它需要独立 Volume + 实例级系统盘开关，
    # 由 main() 通过 StartSandboxInstance / E2B metadata 处理（见 tc05_cbs_volume.py）。
    _ = with_cbs  # 保留签名，实体挂载在实例阶段完成
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


def run_bench(sbx, script: str, label: str, dirs: str = BENCH_DIRS,
              timeout: int = 3600) -> str:
    """执行基准命令。超时不抛异常（COS 小文件可能极慢），返回已拿到的输出。"""
    script = script.replace("__DIRS__", dirs)
    t0 = time.time()
    wrapper = ("cat > /tmp/b.sh <<'AGSEOF'\n" + script
               + "\nAGSEOF\nbash /tmp/b.sh < /dev/null")
    try:
        code, out, err = E2B.run(sbx, wrapper, user="root", timeout=timeout)
    except Exception as exc:  # noqa: BLE001 - 大文件/慢存储可能超时，记录后继续
        print(f"----- {label} (wall {time.time() - t0:.1f}s) -----")
        print(f"!! 基准执行失败/超时: {type(exc).__name__}: {str(exc)[:200]}")
        print("   提示：COS 小文件写入极慢（实测 4K x 2000 约 513s），可改用更小规模或只测 CBS/CFS")
        return ""
    print(f"----- {label} (wall {time.time() - t0:.1f}s, exit={code}) -----")
    print(out)
    if err.strip():
        print("ERR", err[:300])
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--multi", action="store_true", help="双实例并发基准")
    ap.add_argument("--small", action="store_true", help="附加小文件基准")
    ap.add_argument("--with-cbs", action="store_true",
                    help="额外挂载 AgentCBS 数据卷（走 Volume + 系统盘开关，需 --cbs-volume 或自动创建）")
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

    from e2b import Sandbox

    # ---- AgentCBS：独立 Volume + 系统盘开关 ----
    cbs_volume_id = None
    if args.with_cbs:
        from scripts.tc05_cbs_volume import create_volume, wait_active
        cl = ags._client  # AgsClient，支持 call_json
        vol = create_volume(cl, f"{CFG.run_prefix}-cbs-{int(time.time())}")
        wait_active(cl, vol["VolumeId"])
        cbs_volume_id = vol["VolumeId"]
        print(f"AgentCBS 数据卷 ACTIVE: {cbs_volume_id}")

    try:
        if cbs_volume_id:
            sbx1 = Sandbox.create(template=name, timeout=7200, metadata={
                "x-ags-agent-cbs-system-disk": "true",
                "x-storage": json.dumps([{
                    "name": "agent-data",
                    "volume": {"volumeId": cbs_volume_id},
                    "mountPath": "/workspace/data",
                }]),
            })
            print(f"实例1(带CBS) {sbx1.sandbox_id}")
        else:
            iid1 = start_instance(ags, name)
            cleanup.instance(ags, iid1)
            print(f"实例1 RUNNING {iid1}")
            sbx1 = Sandbox.create(template=name, timeout=7200)
    except Exception as exc:  # noqa: BLE001
        print("启动实例失败:", str(exc)[:300])
        return 1
    cleanup.sandbox(sbx1)
    print(f"sandbox1 {sbx1.sandbox_id}")

    try:
        return _run_benches(ags, cleanup, name, sbx1, args, cbs_volume_id)
    finally:
        # CBS 为 RWO：必须确保实例停止，否则卷一直被视为占用，下次挂载 409
        try:
            sbx1.kill()
        except Exception:  # noqa: BLE001
            pass
        if cbs_volume_id:
            print(f"[cbs] 已停止实例，卷 {cbs_volume_id} 应释放（Retain 策略数据保留）")


def _run_benches(ags, cleanup, name, sbx1, args, cbs_volume_id) -> int:
    from e2b import Sandbox

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
        o1 = E2B.run(sbx1, "ls /mnt/vt-cfs /mnt/vt-cos", user="root", timeout=60)[1]
        o2 = E2B.run(sbx2, "ls /mnt/vt-cfs /mnt/vt-cos", user="root", timeout=60)[1]
        print("M1 sees:", o1)
        print("M2 sees:", o2)
    else:
        bdirs = BENCH_DIRS_CBS if cbs_volume_id else BENCH_DIRS
        run_bench(sbx1, BENCH_SEQ, "single-256MiB", bdirs)
        if args.small:
            run_bench(sbx1, BENCH_SMALL, "single-smallfile", bdirs)
    return 0


if __name__ == "__main__":
    sys.exit(main())
