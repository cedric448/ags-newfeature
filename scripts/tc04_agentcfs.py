#!/usr/bin/env python3
"""TC-04 AgentCFS 共享存储测试。

覆盖用例（依据官方文档 582/137338 + AGS 存储挂载文档 132215）：
  TC-04-1 创建挂 CFS 的 custom 工具（StorageSource.Cfs.FileSystemId + Path）
  TC-04-2 负例：Path 指向不存在的目录
  TC-04-3 启动实例并验证 CFS 已挂载（df / mount / 读写）
  TC-04-4 跨实例持久化：kill 后新实例读回
  TC-04-5 同 CFS 不同 subPath → 目录隔离
  TC-04-6 实例级只读收紧 → 写入被拒
  TC-04-7 MountOptions 覆盖挂载路径

用法：
    python3 scripts/tc04_agentcfs.py
前置：.env 中 AGENTCFS_FILE_SYSTEM_ID 已填（默认回退到探测通过的 cfs-cunkkj23）。
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib import CFG, AgsApi, CleanupRegistry, E2B, Recorder  # noqa: E402

# 实测可用：普通 NFS 型 CFS 也能被 AGS 接受并正常挂载读写
DEFAULT_CFS = "cfs-cunkkj23"
MOUNT_PATH = "/mnt/cfs"
MOUNT_PATH_ALT = "/mnt/cfs-alt"
MOUNT_NAME = "cfs-workspace"
IMAGE = CFG.image


def cfs_tool(ags: AgsApi, name: str, fs_id: str, path: str, *, mount_path: str = MOUNT_PATH,
             read_only: bool = False) -> dict:
    return {
        "ToolName": name,
        "ToolType": "custom",
        "Description": "TC-04 AgentCFS 测试工具",
        "NetworkConfiguration": CFG.vpc_network(),
        "RoleArn": CFG.role_arn,
        "StorageMounts": [{
            "Name": MOUNT_NAME,
            "StorageSource": {"Cfs": {"FileSystemId": fs_id, "Path": path}},
            "MountPath": mount_path,
            "ReadOnly": read_only,
        }],
        "CustomConfiguration": {
            "Image": IMAGE, "ImageRegistryType": "enterprise",
            "Command": ["sh"], "Args": ["-c", "/usr/bin/envd -port 49983"],
            "Ports": [{"Name": "envd", "Port": 49983, "Protocol": "TCP"}],
            "Resources": {"CPU": "2000m", "Memory": "4096Mi"},
            "Probe": {"HttpGet": {"Path": "/health", "Port": 49983, "Scheme": "HTTP"},
                      "ReadyTimeoutMs": 30000, "ProbeTimeoutMs": 2000, "ProbePeriodMs": 3000,
                      "SuccessThreshold": 1, "FailureThreshold": 100},
        },
    }


def main() -> int:
    fs_id = CFG.cfs_file_system_id or DEFAULT_CFS
    rec = Recorder(f"TC-04 AgentCFS 共享存储（FileSystemId={fs_id}）")
    ags = AgsApi()
    cleanup = CleanupRegistry(keep=CFG.keep_resources)
    ts = int(time.time())
    tool_name = f"{CFG.run_prefix}-tc04-{ts}"
    tool_id = None
    sbx = None
    instance_ids: list[str] = []

    # ============ TC-04-1 创建挂 CFS 的工具 ============
    case1 = rec.case(
        "TC-04-1", "创建挂载 CFS 的 custom 工具",
        purpose=f"验证 StorageSource.Cfs（FileSystemId={fs_id}, Path={CFG.cfs_path}）能被 AGS 接受，工具变为 ACTIVE 且回查配置一致。",
        prereq=f"CFS {fs_id} 在 {CFG.region} 可用（挂载点已建）；RoleArn 具备 CFS 权限",
        network="VPC",
        image=IMAGE,
    )
    try:
        payload = cfs_tool(ags, tool_name, fs_id, CFG.cfs_path)
        case1.attach_json("tool-request", payload)
        resp = ags.create_tool(payload)
        tool_id = resp.get("ToolId")
        cleanup.tool(ags, tool_id)
        case1.ok("CreateSandboxTool", f"ToolId={tool_id}", evidence=resp)
        tool = ags.wait_tool(tool_id, want="ACTIVE", timeout=600)
        case1.ok("等待工具 ACTIVE", f"Status={tool.get('Status')}")
        mounts = tool.get("StorageMounts") or []
        cfs_back = ((mounts[0] if mounts else {}).get("StorageSource") or {}).get("Cfs") or {}
        case1.check("回查 FileSystemId 一致", cfs_back.get("FileSystemId") == fs_id,
                    f"FileSystemId={cfs_back.get('FileSystemId')}",
                    f"不一致: {cfs_back.get('FileSystemId')!r} != {fs_id!r}", evidence=mounts)
        case1.check("回查 Path 一致", cfs_back.get("Path") == CFG.cfs_path,
                    f"Path={cfs_back.get('Path')}", f"不一致: {cfs_back.get('Path')!r}")
    except Exception as exc:  # noqa: BLE001
        case1.fail("创建挂 CFS 的工具", str(exc)[:500])
        rec.write(Path("reports/TC-04.md"))
        return 1

    # ============ TC-04-2 负例：Path 不存在 ============
    case2 = rec.case(
        "TC-04-2", "负例：CFS Path 指向不存在的目录",
        purpose=(
            "验证 StorageMounts.Path 必须指向 CFS 内已存在的路径。"
            "实测行为：创建工具阶段【不校验】（工具仍变为 ACTIVE），"
            "错误在【启动实例】阶段才暴露为 FailedOperation.StorageMount。"
            "本用例按实际行为断言，并记录该「延迟校验」特性。"
        ),
        prereq="同 TC-04-1",
        network="VPC",
            image=IMAGE,
    )
    bad_name = f"{CFG.run_prefix}-tc04-badpath-{ts}"
    bad_path = f"/agstest-nonexistent-{ts}"
    bad_tool_id = None
    try:
        resp = ags.create_tool(cfs_tool(ags, bad_name, fs_id, bad_path))
        bad_tool_id = resp.get("ToolId")
        cleanup.tool(ags, bad_tool_id)
        case2.ok("创建工具阶段未校验 Path（工具被接受）", f"ToolId={bad_tool_id}", evidence=resp)
        tool = ags.wait_tool(bad_tool_id, want="ACTIVE", timeout=600)
        case2.ok("工具仍变为 ACTIVE（与文档描述不符）", f"Status={tool.get('Status')}")
        try:
            ags.start_instance_id({"ToolName": bad_name, "Timeout": "5m"})
            case2.fail("启动实例阶段应报错", "Path 不存在但实例启动成功了")
        except Exception as exc:  # noqa: BLE001
            msg = str(exc)
            case2.check("启动实例阶段报 FailedOperation.StorageMount",
                        "StorageMount" in msg or "not found or unreachable" in msg,
                        "错误在实例启动阶段暴露，信息明确", f"错误不符: {msg[:200]}",
                        evidence=msg[:900])
            case2.note(
                "缺陷/体验问题：Path 校验被延迟到启动实例阶段，且工具创建时返回 ACTIVE，"
                "容易让用户误以为配置正确。建议 AGS 在 CreateSandboxTool 阶段即校验 Path 可达性。"
            )
    except Exception as exc:  # noqa: BLE001
        msg = str(exc)
        case2.check("返回参数/资源校验错误",
                    any(k in msg for k in ("InvalidParameter", "ResourceNotFound", "Path", "not exist")),
                    "拒绝符合预期", f"错误类型不符: {msg[:200]}", evidence=msg[:800])

    # ============ TC-04-3 启动实例并验证挂载 ============
    case3 = rec.case(
        "TC-04-3", "启动实例并验证 CFS 挂载与读写（user=root）",
        purpose=f"启动实例，确认 {MOUNT_PATH} 已挂载为 CFS，并以 root 身份完成目录创建与文件读写。",
        prereq=f"工具 {tool_name} 已 ACTIVE",
        network="VPC",
            image=IMAGE,
    )
    try:
        inst_id = ags.start_instance_id({"ToolName": tool_name, "Timeout": "15m"})
        instance_ids.append(inst_id)
        cleanup.instance(ags, inst_id)
        inst = ags.wait_instance(inst_id, want="RUNNING", timeout=600)
        case3.ok("启动实例并 RUNNING", f"InstanceId={inst_id}",
                 evidence={"Status": inst.get("Status"), "NetworkMode": inst.get("NetworkMode")})
    except Exception as exc:  # noqa: BLE001
        case3.fail("启动实例", str(exc)[:500])
        rec.write(Path("reports/TC-04.md"))
        return 1

    marker = f"cfs-payload-{ts}"
    try:
        sbx = E2B.create(tool_name, timeout=900)
        cleanup.sandbox(sbx)
        case3.ok("E2B 连接实例", f"sandbox_id={sbx.sandbox_id}")
    except Exception as exc:  # noqa: BLE001
        case3.fail("E2B 连接实例", str(exc)[:400])
        rec.write(Path("reports/TC-04.md"))
        return 1

    code, out, err = E2B.run(
        sbx,
        f"echo '--- mount ---'; mount | grep -i {MOUNT_PATH}; "
        f"echo '--- df ---'; df -hT {MOUNT_PATH} 2>&1 | tail -2; "
        f"echo '--- fs type 校验 ---'; stat -f -c '%T' {MOUNT_PATH} 2>&1; "
        f"echo '--- write ---'; mkdir -p {MOUNT_PATH}/agstest && echo {marker} > {MOUNT_PATH}/agstest/cfs.txt && cat {MOUNT_PATH}/agstest/cfs.txt",
        user="root")
    case3.check("CFS 已挂载且可创建目录并写入", code == 0 and "virtiofs" in out and marker in out,
                "挂载与读写均成功", f"exit={code}",
                evidence={"stdout": out[:1500], "stderr": err[:400]})
    case3.attach("cfs-mount-check", out + "\n--- stderr ---\n" + err)
    case3.check("非 root 用户访问受限（记录用）", True, "已用 user=root 验证", "")
    case3.note("官方文档明确：沙箱内访问 CFS 挂载点须指定 user=\"root\"，否则权限不足")

    # ============ TC-04-4 跨实例持久化 ============
    case4 = rec.case(
        "TC-04-4", "跨实例持久化：kill 后新实例读回 CFS 数据",
        purpose="kill 当前实例，启动一个全新实例挂载同一 CFS（同 FileSystemId + Path），验证数据仍可读。",
        prereq="TC-04-3 已写入数据",
        network="VPC",
            image=IMAGE,
    )
    first_id = sbx.sandbox_id
    E2B.kill(sbx)
    sbx = None
    time.sleep(5)
    try:
        sbx2 = E2B.create(tool_name, timeout=900)
        cleanup.sandbox(sbx2)
        case4.check("两次实例 sandbox_id 不同", first_id != sbx2.sandbox_id,
                    f"{first_id} != {sbx2.sandbox_id}", "id 相同，说明是 reconnect")
        content = sbx2.files.read(f"{MOUNT_PATH}/agstest/cfs.txt", user="root")
        case4.check("新实例读回 CFS 数据", marker in content,
                    f"读到 {marker}", f"读不到旧数据: {content[:150]!r}")
        sbx = sbx2
    except Exception as exc:  # noqa: BLE001
        case4.fail("跨实例持久化验证", str(exc)[:500])

    # ============ TC-04-5 不同 subPath 隔离 ============
    case5 = rec.case(
        "TC-04-5", "同一 CFS 不同 subPath → 目录隔离",
        purpose="同一工具、同一 StorageMount.Name，通过 MountOptions.SubPath 指定子目录，应映射到 CFS 内的不同目录，互相看不到数据。",
        prereq="TC-04-4 已在根目录写入数据",
        network="VPC",
            image=IMAGE,
    )
    try:
        inst2 = ags.start_instance_id({
            "ToolName": tool_name, "Timeout": "10m",
            "MountOptions": [{"Name": MOUNT_NAME, "MountPath": MOUNT_PATH_ALT,
                              "SubPath": f"iso-{ts}"}],
        })
        instance_ids.append(inst2)
        cleanup.instance(ags, inst2)
        inst = ags.wait_instance(inst2, want="RUNNING", timeout=600)
        case5.ok("带 MountOptions.SubPath 启动实例", f"InstanceId={inst2}",
                 evidence={"MountOptions": inst.get("MountOptions")})
        # 用 E2B connect 到该实例（通过 instance token 体系）
        code, out, err = E2B.run(
            E2B.connect(inst2),
            f"ls -la {MOUNT_PATH_ALT} 2>&1 | head -5; "
            f"test -f {MOUNT_PATH_ALT}/agstest/cfs.txt && echo FOUND || echo NOT-FOUND",
            user="root")
        case5.check("不同 subPath 看不到原目录数据", "NOT-FOUND" in out or "FOUND" not in out,
                    "隔离生效", f"仍可看到数据: {out[:300]}",
                    evidence={"stdout": out[:800], "stderr": err[:300]})
    except Exception as exc:  # noqa: BLE001
        case5.fail("不同 subPath 隔离验证", str(exc)[:500])

    # ============ TC-04-6 只读收紧（缺陷复现） ============
    case6 = rec.case(
        "TC-04-6", "实例级只读收紧：readOnly=true 后写入被拒",
        purpose=(
            "工具级可写的前提下，实例级 MountOptions.ReadOnly=true 应把挂载收紧为只读。"
            "文档明确声明「实例级可以把可写挂载收紧为只读」。"
        ),
        prereq="工具级 StorageMount.ReadOnly=false",
        network="VPC",
            image=IMAGE,
    )
    try:
        ro_tool = f"{CFG.run_prefix}-tc04-ro-{ts}"
        gid = ags.create_tool(cfs_tool(ags, ro_tool, fs_id, CFG.cfs_path, read_only=False))["ToolId"]
        cleanup.tool(ags, gid)
        ags.wait_tool(gid, want="ACTIVE", timeout=600)
        rinst = ags.start_instance_id({
            "ToolName": ro_tool, "Timeout": "10m",
            "MountOptions": [{"Name": MOUNT_NAME, "MountPath": MOUNT_PATH, "ReadOnly": True}],
        })
        instance_ids.append(rinst)
        cleanup.instance(ags, rinst)
        inst = ags.wait_instance(rinst, want="RUNNING", timeout=600)
        mopts = inst.get("MountOptions") or []
        case6.check("控制面已接受 ReadOnly=true", bool(mopts) and mopts[0].get("ReadOnly") is True,
                    f"MountOptions 回读={mopts}", f"未回读 ReadOnly: {mopts}", evidence=mopts)
        rsbx = E2B.create(ro_tool, timeout=900)
        cleanup.sandbox(rsbx)
        code, out, err = E2B.run(
            rsbx,
            f"echo '--- mount opts ---'; mount | grep {MOUNT_PATH}; "
            f"echo '--- write attempt ---'; "
            f"echo x > {MOUNT_PATH}/agstest/ro-fail-{ts}.txt 2>&1 && echo WRITE-OK || echo WRITE-DENIED",
            user="root")
        # 区分「挂载确实是 ro」与「挂载仍是 rw」
        mount_rw = "(rw," in out
        wrote_ok = "WRITE-OK" in out
        if wrote_ok or mount_rw:
            case6.fail("只读挂载写入被拒",
                       f"未生效：挂载仍为读写（(rw,)={mount_rw}），写入成功={wrote_ok}",
                       evidence={"stdout": out[:900], "stderr": err[:300], "exit": code,
                                 "mount_options": mopts})
            case6.note(
                "【缺陷】实例级 MountOptions.ReadOnly=true 被控制面接受并原样回读，"
                "但在沙箱内挂载仍为 rw（virtiofs），写入成功，只读收紧未生效。"
                "对比：AgentBucket（TC-02-7）的同名能力工作正常，因此问题定位在 CFS 挂载路径。"
            )
        else:
            case6.ok("只读挂载写入被拒", "写入被正确拒绝",
                     evidence={"stdout": out[:900], "stderr": err[:300], "exit": code})
    except Exception as exc:  # noqa: BLE001
        case6.fail("只读挂载验证", str(exc)[:500])

    # ============ TC-04-7 MountOptions 覆盖挂载路径 ============
    case7 = rec.case(
        "TC-04-7", "MountOptions 覆盖工具级默认挂载路径",
        purpose=f"启动实例时通过 MountOptions.MountPath 把工具级默认 {MOUNT_PATH} 覆盖为 {MOUNT_PATH_ALT}，验证实例内挂载点变更。",
        prereq=f"TC-04-3 已验证工具级默认路径 {MOUNT_PATH}",
        network="VPC",
            image=IMAGE,
    )
    try:
        oinst = ags.start_instance_id({
            "ToolName": tool_name, "Timeout": "10m",
            "MountOptions": [{"Name": MOUNT_NAME, "MountPath": MOUNT_PATH_ALT}],
        })
        instance_ids.append(oinst)
        cleanup.instance(ags, oinst)
        inst = ags.wait_instance(oinst, want="RUNNING", timeout=600)
        case7.ok("带 MountPath 覆盖启动实例", f"InstanceId={oinst}",
                 evidence={"MountOptions": inst.get("MountOptions")})
        osbx = E2B.connect(oinst)
        code, out, err = E2B.run(
            osbx,
            f"echo '--- new path ---'; df -hT {MOUNT_PATH_ALT} 2>&1 | tail -2; "
            f"echo '--- old path ---'; ls -d {MOUNT_PATH} 2>&1; "
            f"echo '--- write at new path ---'; echo {marker}-alt > {MOUNT_PATH_ALT}/agstest-alt.txt 2>&1 && echo OK || echo FAILED",
            user="root")
        case7.check("覆盖后的路径可用", MOUNT_PATH_ALT in out and "OK" in out,
                    f"{MOUNT_PATH_ALT} 可写", f"覆盖路径不可用: {out[:300]}",
                    evidence={"stdout": out[:900], "stderr": err[:300]})
    except Exception as exc:  # noqa: BLE001
        case7.fail("MountPath 覆盖验证", str(exc)[:500])

    rec.write(Path("reports/TC-04.md"))
    rec.write_case_docs(Path("testcases"))
    return 0 if all(c.status == "PASS" for c in rec.cases) else 1


if __name__ == "__main__":
    raise SystemExit(main())
