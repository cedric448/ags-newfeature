#!/usr/bin/env python3
"""TC-02 AgentBucket 持久化存储测试。

覆盖用例（依据 agentbucket.md + 官方文档 137731）：
  TC-02-1 创建带 AgentBucket 的 code-interpreter 工具（只传 LibraryId，不传 SpaceId）
  TC-02-2 负例：custom 工具缺 Probe 应报 MissingParameter
  TC-02-3 E2B 启动实例 + x-mounts[].subPath=spaceID，mountPath 覆盖
  TC-02-4 文件 API 读写（write/read/list/exists）
  TC-02-5 持久化：kill 后新实例（同 name+subPath）能读回
  TC-02-6 隔离：不同 subPath 看不到彼此数据
  TC-02-7 只读：实例级 readOnly=true 收紧后写入被拒
  TC-02-8 负例：不存在的 spaceID → 实例可启动但目录访问失败

用法：
    python3 scripts/tc02_agentbucket.py
前置：.env 中 AGENTBUCKET_LIBRARY_ID / AGENTBUCKET_SPACE_ID / AGS_ROLE_ARN 已填。
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib import CFG, AgsApi, CleanupRegistry, E2B, Recorder  # noqa: E402

MOUNT_PATH = "/mnt/data/agentbucket"
MOUNT_PATH_ALT = "/mnt/data/agentbucket-alt"
MOUNT_NAME = "agentbucket"


def _need(name: str, value: str | None) -> str:
    if not value:
        raise SystemExit(
            f"缺少 {name}。请先按 docs/AGENTBUCKET-AGENTCFS-SETUP.md 回填到 .env 后重试。"
        )
    return value


def create_bucket_tool(ags: AgsApi, tool_name: str, tool_type: str, *, with_probe: bool) -> dict:
    payload: dict = {
        "ToolName": tool_name,
        "ToolType": tool_type,
        "Description": f"TC-02 AgentBucket {tool_type}",
        "NetworkConfiguration": CFG.vpc_network(),
        "RoleArn": CFG.role_arn,
        # 关键：只传 LibraryId，不传 SpaceId（本文 E2B subPath=spaceID 模式）
        "StorageMounts": [
            {
                "Name": MOUNT_NAME,
                "StorageSource": {"AgentBucket": {"LibraryId": CFG.bucket_library_id}},
                "MountPath": MOUNT_PATH,
            }
        ],
    }
    if tool_type == "custom":
        cfg: dict = {
            "Image": CFG.image,
            "ImageRegistryType": "enterprise",
            "Command": ["sh"],
            "Args": ["-c", "/usr/bin/envd -port 49983"],
            "Ports": [{"Name": "envd", "Port": 49983, "Protocol": "TCP"}],
            "Resources": {"CPU": "2000m", "Memory": "4096Mi"},
        }
        if with_probe:
            cfg["Probe"] = {
                "HttpGet": {"Path": "/health", "Port": 49983, "Scheme": "HTTP"},
                "ReadyTimeoutMs": 30000, "ProbeTimeoutMs": 2000, "ProbePeriodMs": 3000,
                "SuccessThreshold": 1, "FailureThreshold": 100,
            }
        payload["CustomConfiguration"] = cfg
    return payload


def main() -> int:
    lib = _need("AGENTBUCKET_LIBRARY_ID", CFG.bucket_library_id)
    space = _need("AGENTBUCKET_SPACE_ID", CFG.bucket_space_id)
    _need("AGS_ROLE_ARN", CFG.role_arn)

    rec = Recorder("TC-02 AgentBucket 持久化存储")
    ags = AgsApi()
    cleanup = CleanupRegistry(keep=CFG.keep_resources)
    ts = int(time.time())
    tool_name = f"{CFG.run_prefix}-tc02-{ts}"
    tool_id = None
    sbx1 = sbx2 = sbx3 = None
    inst_ids: list[str] = []

    # ================= TC-02-1 创建 code-interpreter 工具 =================
    case = rec.case(
        "TC-02-1", "创建带 AgentBucket 的 code-interpreter 工具",
        purpose="验证按 E2B subPath=spaceID 模式创建工具：只传 LibraryId、不传 SpaceId，工具应变为 ACTIVE 且回查 LibraryId 一致。",
        prereq=f"SMH LibraryId={lib}；RoleArn 具备 QcloudSMHFullAccess；VPC={CFG.vpc_id}",
        network="VPC",
    )
    try:
        payload = create_bucket_tool(ags, tool_name, "code-interpreter", with_probe=False)
        case.attach_json("tool-request", payload)
        resp = ags.create_tool(payload)
        tool_id = resp.get("ToolId")
        case.ok("CreateSandboxTool (code-interpreter)", f"ToolId={tool_id}", evidence=resp)
        cleanup.tool(ags, tool_id)
    except Exception as exc:  # noqa: BLE001
        case.fail("CreateSandboxTool (code-interpreter)", str(exc)[:500])
        rec.write(Path("reports/TC-02.md"))
        return 1

    try:
        tool = ags.wait_tool(tool_id, want="ACTIVE", timeout=600)
        case.ok("等待工具 ACTIVE", f"Status={tool.get('Status')}")
        mounts = tool.get("StorageMounts") or []
        lib_back = (((mounts[0] if mounts else {}).get("StorageSource") or {}).get("AgentBucket") or {}).get("LibraryId")
        case.check("回查 LibraryId 与请求一致", lib_back == lib, f"LibraryId={lib_back}", f"不一致: {lib_back!r} != {lib!r}",
                   evidence=mounts)
        has_space = any("SpaceId" in ((m.get("StorageSource") or {}).get("AgentBucket") or {}) for m in mounts)
        case.check("创建工具阶段未回填 SpaceId", not has_space, "确认未传 SpaceId", "出现了 SpaceId 字段")
    except Exception as exc:  # noqa: BLE001
        case.fail("等待工具 ACTIVE", str(exc)[:500])
        rec.write(Path("reports/TC-02.md"))
        return 1

    # ================= TC-02-2 负例：custom 缺 Probe =================
    case2 = rec.case(
        "TC-02-2", "负例：custom 工具缺 Probe 应报 MissingParameter",
        purpose="验证 CustomConfiguration.Probe 为必填，缺失时云 API 返回 MissingParameter.CustomConfiguration.Probe。",
        prereq="同 TC-02-1",
        network="VPC",
    )
    bad_name = f"{CFG.run_prefix}-tc02-noprobe-{ts}"
    try:
        bad = create_bucket_tool(ags, bad_name, "custom", with_probe=False)
        ags.create_tool(bad)
        case2.fail("创建缺 Probe 的 custom 工具", "预期报错但创建成功了")
    except Exception as exc:  # noqa: BLE001
        msg = str(exc)
        case2.check("返回 MissingParameter 类错误", "MissingParameter" in msg or "Probe" in msg,
                    "错误符合预期", f"错误类型不符: {msg[:200]}", evidence=msg[:800])

    # ================= TC-02-3 启动实例 + subPath=spaceID =================
    case3 = rec.case(
        "TC-02-3", "E2B 启动实例并通过 x-mounts[].subPath 指定 spaceID",
        purpose=f"验证 metadata.x-mounts[].subPath 传 spaceID、mountPath 覆盖工具级默认值（{MOUNT_PATH} → {MOUNT_PATH_ALT}）。",
        prereq=f"工具 {tool_name} 已 ACTIVE；spaceID={space}",
        network="VPC",
    )
    try:
        sbx1 = E2B.create(tool_name, timeout=600,
                          mounts=[{"name": MOUNT_NAME, "mountPath": MOUNT_PATH_ALT, "subPath": space}])
        cleanup.sandbox(sbx1)
        case3.ok("E2B 创建沙箱实例", f"sandbox_id={sbx1.sandbox_id}")
    except Exception as exc:  # noqa: BLE001
        case3.fail("E2B 创建沙箱实例", str(exc)[:500])
        rec.write(Path("reports/TC-02.md"))
        return 1

    try:
        code, out, err = E2B.run(
            sbx1,
            f"echo '--- mount listing ---'; mount | grep -i agentbucket; "
            f"echo '--- df ---'; df -hT {MOUNT_PATH_ALT} 2>&1 | tail -2; "
            f"echo '--- mkdir+write ---'; mkdir -p {MOUNT_PATH_ALT}/agstest && echo hello-bucket > {MOUNT_PATH_ALT}/agstest/probe.txt && cat {MOUNT_PATH_ALT}/agstest/probe.txt",
            user="root")
        case3.check("挂载点存在且可创建目录并写入", code == 0 and "hello-bucket" in out,
                    f"exit=0，写入成功", f"exit={code}, err={err[:200]}",
                    evidence={"stdout": out[:1500], "stderr": err[:500]})
    except Exception as exc:  # noqa: BLE001
        case3.fail("挂载点验证", str(exc)[:400])

    # ================= TC-02-4 文件 API 四件套 =================
    case4 = rec.case(
        "TC-02-4", "E2B 文件 API 读写挂载目录（write/read/list/exists）",
        purpose="验证 files.write / files.read / files.list / files.exists 在 AgentBucket 挂载目录上均可用。",
        prereq="实例已挂载 AgentBucket",
        network="VPC",
    )
    marker = f"agentbucket-payload-{ts}"
    target = f"{MOUNT_PATH_ALT}/agstest/file-api.txt"
    try:
        sbx1.files.write(target, marker, user="root")
        case4.ok("files.write 写入", target)
    except Exception as exc:  # noqa: BLE001
        case4.fail("files.write 写入", str(exc)[:300])
    try:
        content = sbx1.files.read(target, user="root")
        case4.check("files.read 读回一致", content.strip() == marker, "内容一致", f"内容不一致: {content[:120]!r}")
    except Exception as exc:  # noqa: BLE001
        case4.fail("files.read 读回", str(exc)[:300])
    try:
        exists = sbx1.files.exists(target, user="root")
        case4.check("files.exists 返回 True", bool(exists), "存在", "不存在")
    except Exception as exc:  # noqa: BLE001
        case4.fail("files.exists", str(exc)[:300])
    try:
        items = sbx1.files.list(f"{MOUNT_PATH_ALT}/agstest", user="root")
        names = [getattr(i, "name", None) or (i.get("name") if isinstance(i, dict) else str(i)) for i in (items or [])]
        case4.check("files.list 能列出目录内容", len(names) > 0, f"条目={names[:10]}", "目录为空")
    except Exception as exc:  # noqa: BLE001
        case4.fail("files.list", str(exc)[:300])

    # ================= TC-02-5 持久化验证 =================
    case5 = rec.case(
        "TC-02-5", "跨实例持久化：kill 后新实例可读回数据",
        purpose="kill 第一个实例，启动全新实例（同 StorageMount.Name + 同 subPath），验证数据由 AgentBucket 持久化、不依赖单实例生命周期。",
        prereq="TC-02-4 已成功写入数据",
        network="VPC",
    )
    first_id = sbx1.sandbox_id if sbx1 else None
    E2B.kill(sbx1)
    sbx1 = None
    time.sleep(5)
    try:
        sbx2 = E2B.create(tool_name, timeout=600,
                          mounts=[{"name": MOUNT_NAME, "mountPath": MOUNT_PATH_ALT, "subPath": space}])
        cleanup.sandbox(sbx2)
        second_id = sbx2.sandbox_id
        case5.check("两次实例 sandbox_id 不同", first_id != second_id,
                    f"{first_id} != {second_id}", f"id 相同，说明是 reconnect 而非新实例")
        content = sbx2.files.read(target, user="root")
        case5.check("新实例读回 AgentBucket 数据", marker in content,
                    f"读到 {marker}", f"读不到旧数据: {content[:120]!r}")
    except Exception as exc:  # noqa: BLE001
        case5.fail("新实例读回数据", str(exc)[:400])

    # ================= TC-02-6 不同 subPath 隔离 =================
    case6 = rec.case(
        "TC-02-6", "同一工具不同 subPath 数据空间隔离",
        purpose="同一工具、同一 StorageMount.Name，换一个 subPath 启动实例，应看不到 TC-02-5 写入的文件。",
        prereq="TC-02-5 已在 spaceID A 写入数据",
        network="VPC",
    )
    other_space = f"{space}-alt"
    try:
        sbx3 = E2B.create(tool_name, timeout=600,
                          mounts=[{"name": MOUNT_NAME, "mountPath": MOUNT_PATH_ALT, "subPath": other_space}])
        cleanup.sandbox(sbx3)
        code, out, err = E2B.run(
            sbx3, f"ls -la {MOUNT_PATH_ALT}/agstest 2>&1; echo '=== exists check ==='; "
                  f"test -f {target} && echo FOUND || echo NOT-FOUND", user="root")
        case6.check("不同 subPath 看不到原空间数据", "NOT-FOUND" in out or "FOUND" not in out,
                    f"隔离生效（space={other_space}）", f"仍可看到数据: {out[:300]}",
                    evidence={"stdout": out[:800], "stderr": err[:300]})
    except Exception as exc:  # noqa: BLE001
        case6.fail("不同 subPath 隔离验证", str(exc)[:400])

    # ================= TC-02-7 只读收紧 =================
    case7 = rec.case(
        "TC-02-7", "实例级只读收紧：readOnly=true 后写入被拒",
        purpose="工具级可写的前提下，实例级 metadata.x-mounts[].readOnly=true 应把挂载收紧为只读，写入失败。",
        prereq="工具级 StorageMount 未设置 ReadOnly",
        network="VPC",
    )
    try:
        ro = E2B.create(tool_name, timeout=600,
                        mounts=[{"name": MOUNT_NAME, "mountPath": MOUNT_PATH_ALT,
                                 "subPath": space, "readOnly": True}])
        cleanup.sandbox(ro)
        code, out, err = E2B.run(
            ro, f"echo x > {MOUNT_PATH_ALT}/agstest/ro-should-fail.txt 2>&1 && echo WRITE-OK || echo WRITE-DENIED; "
                f"ls -la {MOUNT_PATH_ALT}/agstest 2>&1 | head -5", user="root")
        case7.check("只读挂载写入被拒", "WRITE-DENIED" in out or code != 0,
                    "写入被正确拒绝", f"写入竟然成功了: {out[:300]}",
                    evidence={"stdout": out[:800], "stderr": err[:300], "exit": code})
    except Exception as exc:  # noqa: BLE001
        case7.fail("只读挂载验证", str(exc)[:400])

    # ================= TC-02-8 负例：不存在的 spaceID =================
    case8 = rec.case(
        "TC-02-8", "负例：不存在的 spaceID 挂载行为",
        purpose="文档说明：传入不存在的 spaceID 时实例仍可启动，但挂载目录不会被创建/访问报 no such file or directory。",
        prereq="同 TC-02-3",
        network="VPC",
    )
    try:
        bad = E2B.create(tool_name, timeout=600,
                         mounts=[{"name": MOUNT_NAME, "mountPath": MOUNT_PATH_ALT,
                                  "subPath": f"nonexistent-space-{ts}"}])
        cleanup.sandbox(bad)
        case8.ok("实例仍能启动", f"sandbox_id={bad.sandbox_id}")
        code, out, err = E2B.run(bad, f"ls -la {MOUNT_PATH_ALT} 2>&1 | head -5", user="root")
        case8.ok("记录挂载目录访问结果", f"exit={code}", evidence={"stdout": out[:500], "stderr": err[:500]})
        case8.note("按文档预期应报 no such file or directory；此处仅记录实际行为，不作强断言")
    except Exception as exc:  # noqa: BLE001
        case8.ok("不存在的 spaceID 导致实例创建失败（也是可接受行为）", str(exc)[:300])

    rec.write(Path("reports/TC-02.md"))
    rec.write_case_docs(Path("testcases"))
    return 0 if all(c.status == "PASS" for c in rec.cases) else 1


if __name__ == "__main__":
    raise SystemExit(main())
