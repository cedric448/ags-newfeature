#!/usr/bin/env python3
"""AgentCBS 数据盘接入辅助：创建 Volume + 带系统盘开关启动实例。

参考 agscbs-disk.md / agscbs-sys.md。核心要点：

1. AgentCBS **数据盘**走独立的 `Volume` 资源，**不走** VolumeTemplate 的 StorageMounts；
2. 启动实例时必须**同时**提供：
   - StorageMounts[].Volume.VolumeId + MountPath
   - Metadata: x-ags-agent-cbs-system-disk = "true"   ← 少这个就报
     "AgentCBS Volume requires an AgentCBS SystemDisk instance"
3. RWO 独占：卷被占用时二次挂载 409 ResourceInUse，需先停原实例并等卷释放。

用法：
    python3 scripts/tc05_cbs_volume.py --create          # 创建 20Gi CBS 数据卷
    python3 scripts/tc05_cbs_volume.py --status          # 查询卷状态
    python3 scripts/tc05_cbs_volume.py --delete <VID>    # 删除（会清数据）
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tencentcloud.ags.v20250920 import ags_client  # noqa: E402
from tencentcloud.common import credential  # noqa: E402
from tencentcloud.common.exception.tencent_cloud_sdk_exception import (  # noqa: E402
    TencentCloudSDKException,
)
from tencentcloud.common.profile.client_profile import ClientProfile  # noqa: E402
from tencentcloud.common.profile.http_profile import HttpProfile  # noqa: E402

from lib import CFG  # noqa: E402


def client():
    cred = credential.Credential(CFG.secret_id, CFG.secret_key)
    http = HttpProfile(endpoint="ags.tencentcloudapi.com")
    return ags_client.AgsClient(cred, CFG.region, ClientProfile(httpProfile=http))


def create_volume(cl, name: str, capacity: str = "20Gi") -> dict:
    payload = {
        "VolumeName": name,
        "StorageType": "AgentCbs",          # 注意大小写
        "Storage": {"AgentCbs": {"Capacity": capacity}},
        "AccessMode": "ReadWriteOnce",       # CBS 固定 RWO
        "ClientToken": f"{name}-{int(time.time())}",
    }
    resp = cl.call_json("CreateVolume", payload)["Response"]
    return resp.get("Volume") or resp


def describe_volume(cl, vid: str) -> dict | None:
    resp = cl.call_json("DescribeVolumeList", {"VolumeIds": [vid], "Limit": 1})["Response"]
    vs = resp.get("VolumeSet") or []
    return vs[0] if vs else None


def wait_active(cl, vid: str, timeout: float = 300) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        v = describe_volume(cl, vid)
        if v and v.get("Status") == "ACTIVE":
            return v
        if v and v.get("Status") == "FAILED":
            raise RuntimeError(f"卷 {vid} 创建失败")
        time.sleep(5)
    raise TimeoutError(f"等待卷 {vid} ACTIVE 超时")


# ---------- 挂载示例（供其它脚本 import） ----------

CBS_SYSTEM_DISK_KEY = "x-ags-agent-cbs-system-disk"
CBS_MOUNT_PATH = "/workspace/data"


def start_instance_with_cbs(cl, tool_id: str, volume_id: str,
                            mount_path: str = CBS_MOUNT_PATH,
                            timeout: str = "600s") -> str:
    """Cloud API 方式：同时传 StorageMounts 和系统盘开关。"""
    payload = {
        "ToolId": tool_id,
        "Timeout": timeout,
        "StorageMounts": [
            {"Name": "agent-data", "Volume": {"VolumeId": volume_id}, "MountPath": mount_path}
        ],
        "Metadata": [{"Name": CBS_SYSTEM_DISK_KEY, "Value": "true"}],
    }
    resp = cl.call_json("StartSandboxInstance", payload)["Response"]
    return (resp.get("Instance") or {}).get("InstanceId") or resp.get("InstanceId")


def create_sandbox_with_cbs(tool_name: str, volume_id: str,
                            mount_path: str = CBS_MOUNT_PATH, timeout: int = 3600):
    """E2B SDK 方式：metadata 里同时给系统盘开关和 x-storage（小驼峰）。"""
    from lib import ensure_domain  # noqa: PLC0415

    ensure_domain()
    from e2b import Sandbox  # noqa: PLC0415

    return Sandbox.create(
        template=tool_name,
        timeout=timeout,
        metadata={
            CBS_SYSTEM_DISK_KEY: "true",
            "x-storage": json.dumps([{
                "name": "agent-data",
                "volume": {"volumeId": volume_id},   # 注意：volumeId 小驼峰
                "mountPath": mount_path,
            }]),
        },
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--create", action="store_true", help="创建 CBS 数据卷")
    ap.add_argument("--name", default="cedricbwang-cbs-bench", help="卷名")
    ap.add_argument("--capacity", default="20Gi", help="容量，如 20Gi")
    ap.add_argument("--status", action="store_true", help="查询卷状态")
    ap.add_argument("--delete", metavar="VOLUME_ID", help="删除卷（清数据）")
    args = ap.parse_args()
    cl = client()

    if args.create:
        v = create_volume(cl, args.name, args.capacity)
        print("Created:", v.get("VolumeId"), v.get("Status"))
        v = wait_active(cl, v["VolumeId"])
        print("ACTIVE:", json.dumps(v, ensure_ascii=False))
        print("\n记住 VolumeId:", v["VolumeId"])
        return 0

    if args.status:
        resp = cl.call_json("DescribeVolumeList", {"Limit": 100})["Response"]
        for v in resp.get("VolumeSet") or []:
            print(f"{v['VolumeId']}  {v.get('VolumeName',''):30s} {v['StorageType']:8s} "
                  f"{v['Status']:10s} mounted={v.get('MountedInstanceId')}")
        return 0

    if args.delete:
        cl.call_json("DeleteVolume", {"VolumeId": args.delete})
        print("delete requested:", args.delete)
        return 0

    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
