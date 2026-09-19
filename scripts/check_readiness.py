#!/usr/bin/env python3
"""就绪检查：确认新镜像与新 CFS 是否可用于 AGS 测试。

检查项：
  1. 镜像 manifest 是否存在（通过 TCR API 查询 tag 列表）
  2. 镜像是否包含 envd（通过本地 docker，若有）
  3. CFS 是否有挂载点（DescribeMountTargets）
  4. 端到端：能否用该镜像 + 该 CFS 创建工具 / 启动实例 / 挂载读写

用法：
    python3 scripts/check_readiness.py            # 只做检查
    python3 scripts/check_readiness.py --e2e      # 额外做一次端到端冒烟
"""
from __future__ import annotations

import argparse
import base64
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib import CFG, AgsApi, E2B  # noqa: E402

OK = "✅"
NG = "❌"


def tcr_image_tags(registry_id: str, namespace: str, repo: str) -> list[str] | None:
    from tencentcloud.common import credential
    from tencentcloud.common.profile.client_profile import ClientProfile
    from tencentcloud.common.profile.http_profile import HttpProfile
    from tencentcloud.tcr.v20190924 import tcr_client

    cred = credential.Credential(CFG.secret_id, CFG.secret_key)
    c = tcr_client.TcrClient(cred, "ap-beijing",
                             ClientProfile(httpProfile=HttpProfile(endpoint="tcr.tencentcloudapi.com")))
    try:
        r = c.call_json("DescribeImages", {
            "RegistryId": registry_id, "NamespaceName": namespace,
            "RepositoryName": repo, "Limit": 50,
        })
        return [i["ImageVersion"] for i in r["Response"].get("ImageInfoList", [])]
    except Exception as exc:  # noqa: BLE001
        print(f"  查询镜像出错: {str(exc)[:200]}")
        return None


def check_image() -> bool:
    print("\n[1] 检查镜像")
    image = CFG.image
    print(f"  IMAGE = {image}")
    _, _, tag = image.rpartition(":")
    path = image.split("/", 1)[1].rsplit(":", 1)[0]
    namespace, _, repo = path.partition("/")
    if not repo:
        namespace, repo = "library", namespace
    print(f"  namespace={namespace} repo={repo} tag={tag}")

    tags = tcr_image_tags(CFG.tcr_instance or "tcr-mvlaq1sq", namespace, repo)
    if tags is None:
        print(f"  {NG} 无法查询 tag 列表")
        return False
    print(f"  远端 tags = {tags}")
    if tag not in tags:
        print(f"  {NG} tag '{tag}' 不存在（仓库共有 {len(tags)} 个 tag）")
        return False
    print(f"  {OK} tag '{tag}' 存在")
    return True


def check_image_has_envd() -> bool:
    print("\n[2] 检查镜像是否包含 envd（本地 docker，可选）")
    r = subprocess.run(["which", "docker"], capture_output=True, text=True)
    if not r.stdout.strip():
        print("  ⚠ 本地无 docker，跳过（AGS 侧会用 AGT_ENVD_PATH 指定的路径）")
        return True
    if subprocess.run(["docker", "info"], capture_output=True).returncode != 0:
        print("  ⚠ docker daemon 未运行，跳过")
        return True
    print("  拉取镜像（可能需要 VPN）...")
    pull = subprocess.run(["docker", "pull", CFG.image], capture_output=True, text=True, timeout=600)
    if pull.returncode != 0:
        print(f"  {NG} 拉取失败: {pull.stderr.strip()[:300]}")
        print("     若为认证问题，请确认 namespace 权限或 docker login")
        return False
    print(f"  {OK} 拉取成功")
    chk = subprocess.run(
        ["docker", "run", "--rm", "--entrypoint", "sh", CFG.image, "-c",
         f"ls -l {CFG.envd_path} && {CFG.envd_path} -version 2>&1 | head -2"],
        capture_output=True, text=True, timeout=120)
    if chk.returncode == 0:
        print(f"  {OK} 镜像内 {CFG.envd_path} 存在: {chk.stdout.strip()[:150]}")
        return True
    print(f"  {NG} 镜像内未找到 {CFG.envd_path}: {chk.stderr.strip()[:200]}")
    print("     提示：AGS 自定义沙箱需要 envd，或通过镜像卷挂载 envd")
    return False


def check_cfs() -> bool:
    print("\n[3] 检查 CFS 挂载点")
    from tencentcloud.common import credential
    from tencentcloud.common.profile.client_profile import ClientProfile
    from tencentcloud.common.profile.http_profile import HttpProfile
    from tencentcloud.cfs.v20190719 import cfs_client

    fs = CFG.cfs_file_system_id
    if not fs:
        print(f"  {NG} 未配置 AGENTCFS_FILE_SYSTEM_ID")
        return False
    print(f"  FileSystemId = {fs}  Path = {CFG.cfs_path}")
    if CFG.cfs_endpoint_id:
        print(f"  接入点 ID    = {CFG.cfs_endpoint_id}")
    cred = credential.Credential(CFG.secret_id, CFG.secret_key)
    c = cfs_client.CfsClient(cred, "ap-beijing",
                             ClientProfile(httpProfile=HttpProfile(endpoint="cfs.tencentcloudapi.com")))
    try:
        info = c.call_json("DescribeCfsFileSystems", {"Offset": 0, "Limit": 50})
        me = next((x for x in info["Response"].get("FileSystems", []) if x["FileSystemId"] == fs), None)
        if me:
            print(f"  类型: protocol={me.get('Protocol')} storage={me.get('StorageType')} "
                  f"zone={me.get('Zone')} name={me.get('FsName')}")
        else:
            print(f"  {NG} 该地域查不到该文件系统")
            return False
    except Exception as exc:  # noqa: BLE001
        print(f"  ⚠ 查询文件系统详情失败: {str(exc)[:150]}")

    try:
        r = c.call_json("DescribeMountTargets", {"FileSystemId": fs})
        mts = r["Response"].get("MountTargets", [])
    except Exception as exc:  # noqa: BLE001
        print(f"  {NG} 查询挂载点失败: {str(exc)[:200]}")
        return False
    print(f"  挂载点数量 = {len(mts)}")
    for m in mts:
        print(f"    - {m.get('MountTargetId')} vpc={m.get('VpcId')} "
              f"subnet={m.get('SubnetId')} ip={m.get('IpAddress')}")
    if not mts:
        print(f"  {NG} 没有挂载点 —— AGS 会报 no mount targets found for CFS")
        print("     需在 CFS 控制台为该文件系统创建挂载点（建议选 ap-beijing-6 / 与沙箱同 VPC）")
        return False
    print(f"  {OK} 至少有一个挂载点")
    return True


def e2e_smoke() -> bool:
    print("\n[4] 端到端冒烟：镜像 + CFS 建工具 → 起实例 → 挂载读写")
    a = AgsApi()
    ts = int(time.time())
    name = f"{CFG.run_prefix}-ready-{ts}"
    payload = {
        "ToolName": name, "ToolType": "custom",
        "Description": "readiness smoke",
        "NetworkConfiguration": CFG.vpc_network(),
        "RoleArn": CFG.role_arn,
        "StorageMounts": [{
            "Name": "cfs", "MountPath": "/mnt/cfs",
            "StorageSource": {"Cfs": {"FileSystemId": CFG.cfs_file_system_id, "Path": CFG.cfs_path}},
        }],
        "CustomConfiguration": {
            "Image": CFG.image, "ImageRegistryType": CFG.image_registry_type,
            "Command": ["sh"], "Args": ["-c", f"{CFG.envd_path} -port 49983"],
            "Ports": [{"Name": "envd", "Port": 49983, "Protocol": "TCP"}],
            "Resources": {"CPU": "2000m", "Memory": "4096Mi"},
            "Probe": {"HttpGet": {"Path": "/health", "Port": 49983, "Scheme": "HTTP"},
                      "ReadyTimeoutMs": 30000, "ProbeTimeoutMs": 2000, "ProbePeriodMs": 3000,
                      "SuccessThreshold": 1, "FailureThreshold": 100},
        },
    }
    tid = iid = None
    sbx = None
    try:
        tid = a.create_tool(payload)["ToolId"]
        print(f"  工具已创建 {tid}，等待 ACTIVE ...")
        t = a.wait_tool(tid, want="ACTIVE", timeout=900)
        print(f"  {OK} 工具 ACTIVE（镜像 digest={(t.get('CustomConfiguration') or {}).get('ImageDigest')}）")
    except Exception as exc:  # noqa: BLE001
        print(f"  {NG} 创建工具失败: {str(exc)[:400]}")
        if tid:
            try:
                a.delete_tool(tid)
            except Exception:  # noqa: BLE001
                pass
        return False
    try:
        iid = a.start_instance_id({"ToolName": name, "Timeout": "10m"})
        print(f"  实例 {iid}，等待 RUNNING ...")
        a.wait_instance(iid, want="RUNNING", timeout=900)
        print(f"  {OK} 实例 RUNNING")
        sbx = E2B.create(name, timeout=600)
        code, out, err = E2B.run(
            sbx,
            "echo '--- mount ---'; mount | grep /mnt/cfs; "
            "echo '--- write ---'; mkdir -p /mnt/cfs/agstest && "
            f"echo ready-{ts} > /mnt/cfs/agstest/ready.txt && cat /mnt/cfs/agstest/ready.txt",
            user="root")
        if code == 0 and f"ready-{ts}" in out:
            print(f"  {OK} CFS 挂载与读写成功")
            print("     " + out.strip().replace("\n", "\n     ")[:400])
            return True
        print(f"  {NG} CFS 读写失败 exit={code}")
        print(f"     stdout={out[:300]}")
        print(f"     stderr={err[:300]}")
        return False
    except Exception as exc:  # noqa: BLE001
        print(f"  {NG} 启动实例/挂载失败: {str(exc)[:400]}")
        return False
    finally:
        if sbx is not None:
            E2B.kill(sbx)
        if iid:
            try:
                a.stop_instance(iid)
            except Exception:  # noqa: BLE001
                pass
        if tid:
            time.sleep(10)
            try:
                a.delete_tool(tid)
                print("  已清理测试资源")
            except Exception as exc:  # noqa: BLE001
                print(f"  ⚠ 清理工具失败: {str(exc)[:150]}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--e2e", action="store_true", help="额外执行端到端冒烟")
    args = ap.parse_args()

    print("=" * 60)
    print("AGS 就绪检查")
    print(f"  region    = {CFG.region}")
    print(f"  image     = {CFG.image}")
    print(f"  CFS       = {CFG.cfs_file_system_id} (path={CFG.cfs_path})")
    print(f"  VPC       = {CFG.vpc_id} / {CFG.subnet_id} / {CFG.security_group_id}")
    print("=" * 60)

    results = {
        "镜像 tag 存在": check_image(),
        "镜像含 envd": check_image_has_envd(),
        "CFS 有挂载点": check_cfs(),
    }
    if args.e2e:
        results["端到端冒烟"] = e2e_smoke()

    print("\n" + "=" * 60)
    print("检查结果")
    for k, v in results.items():
        print(f"  {OK if v else NG} {k}")
    print("=" * 60)
    return 0 if all(results.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
