#!/usr/bin/env python3
"""TC-01 基线：用 TCR 镜像创建 AGS 沙箱工具，并启动实例验证数据面。

用途：打通"创建工具 → 等待 ACTIVE → 启动实例 → 执行命令 → 清理"最小闭环。
用法：
    python3 scripts/tc01_baseline.py            # VPC 模式（默认）
    python3 scripts/tc01_baseline.py --public   # PUBLIC 模式对比
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib import CFG, AgsApi, CleanupRegistry, Recorder, E2B  # noqa: E402

ENVD_CMD = "/usr/bin/envd -port 49983"


def build_tool_payload(name: str, image: str, network: dict) -> dict:
    return {
        "ToolName": name,
        "ToolType": "custom",
        "Description": "AGS 测试基线：TCR 镜像 + envd 探针",
        "NetworkConfiguration": network,
        "DefaultTimeout": "30m",
        "RoleArn": CFG.role_arn,
        "CustomConfiguration": {
            "Image": image,
            "ImageRegistryType": "enterprise",
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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--public", action="store_true", help="使用 PUBLIC 网络模式")
    ap.add_argument("--image", default=None, help="覆盖镜像地址")
    args = ap.parse_args()

    network = CFG.public_network() if args.public else CFG.vpc_network()
    net_label = network["NetworkMode"]
    image = args.image or CFG.image

    rec = Recorder(f"TC-01 基线：AGS 沙箱启动打通（{net_label}）")
    case = rec.case(
        "TC-01",
        f"TCR 镜像创建沙箱工具并启动实例（{net_label}）",
        purpose=(
            f"验证用 TCR 实例 `{CFG.tcr_instance}` 的镜像 `{image}` 能否在 AGS 北京地域"
            f"创建 custom 工具并成功启动沙箱实例，数据面可执行命令。"
            "这是所有后续测试例的前置基线。"
        ),
        prereq=f"腾讯云凭据可用；TCR 镜像可访问；网络模式 {net_label}",
        network=net_label,
        image=image,
    )
    ags = AgsApi()
    cleanup = CleanupRegistry(keep=CFG.keep_resources)

    tool_name = f"{CFG.run_prefix}-tc01-{int(time.time())}"
    tool_id = None
    sbx = None

    # ---- 步骤 1: 创建工具 ----
    t0 = time.time()
    payload = build_tool_payload(tool_name, image, network)
    case.attach_json("tool-request", payload)
    try:
        resp = ags.create_tool(payload)
        tool_id = resp.get("ToolId")
        case.ok("创建沙箱工具 CreateSandboxTool", f"ToolId={tool_id}",
                evidence=resp, duration=time.time() - t0)
        cleanup.tool(ags, tool_id)
    except Exception as exc:  # noqa: BLE001
        case.fail("创建沙箱工具 CreateSandboxTool", str(exc)[:400])
        rec.write(Path(f"reports/TC-01-{net_label}.md"))
        return 1

    # ---- 步骤 2: 等待 ACTIVE ----
    t0 = time.time()
    try:
        tool = ags.wait_tool(tool_id, want="ACTIVE", timeout=600)
        case.ok("等待工具状态 ACTIVE", f"状态={tool.get('Status')}",
                evidence={"Status": tool.get("Status"), "StatusReason": tool.get("StatusReason"),
                          "ImageDigest": (tool.get("CustomConfiguration") or {}).get("ImageDigest")},
                duration=time.time() - t0)
        digest = (tool.get("CustomConfiguration") or {}).get("ImageDigest")
        case.check("镜像 digest 已解析", bool(digest), f"digest={digest}", "digest 为空")
    except Exception as exc:  # noqa: BLE001
        case.fail("等待工具状态 ACTIVE", str(exc)[:400])
        rec.write(Path(f"reports/TC-01-{net_label}.md"))
        return 1

    # ---- 步骤 3: 通过 Cloud API 启动实例 ----
    t0 = time.time()
    instance_id = None
    try:
        resp = ags.start_instance({"ToolName": tool_name, "Timeout": "15m"})
        # StartSandboxInstance 返回 {"Instance": {...}, "RequestId": ...}
        instance_id = (resp.get("Instance") or {}).get("InstanceId") or resp.get("InstanceId")
        case.ok("启动沙箱实例 StartSandboxInstance", f"InstanceId={instance_id}",
                evidence=resp, duration=time.time() - t0)
        cleanup.instance(ags, instance_id)
    except Exception as exc:  # noqa: BLE001
        case.fail("启动沙箱实例 StartSandboxInstance", str(exc)[:400])
        case.note("这是当前已知的阻塞现象 FailedOperation.Timeout，需排查镜像/配额/地域服务状态")
        rec.write(Path(f"reports/TC-01-{net_label}.md"))
        return 1

    # ---- 步骤 4: 等待 RUNNING ----
    t0 = time.time()
    try:
        inst = ags.wait_instance(instance_id, want="RUNNING", timeout=900)
        case.ok("等待实例状态 RUNNING", f"状态={inst.get('Status')}",
                evidence={"Status": inst.get("Status"), "NetworkMode": inst.get("NetworkMode"),
                          "ExpiresAt": inst.get("ExpiresAt"), "StopReason": inst.get("StopReason")},
                duration=time.time() - t0)
    except Exception as exc:  # noqa: BLE001
        case.fail("等待实例状态 RUNNING", str(exc)[:400])
        rec.write(Path(f"reports/TC-01-{net_label}.md"))
        return 1

    # ---- 步骤 5: E2B 数据面执行命令 ----
    t0 = time.time()
    try:
        sbx = E2B.create(tool_name, timeout=600)
        cleanup.sandbox(sbx)
        case.ok("E2B 连接沙箱实例", f"sandbox_id={sbx.sandbox_id}", duration=time.time() - t0)
    except Exception as exc:  # noqa: BLE001
        case.fail("E2B 连接沙箱实例", str(exc)[:400])
        rec.write(Path(f"reports/TC-01-{net_label}.md"))
        return 1

    t0 = time.time()
    try:
        code, out, err = E2B.run(
            sbx,
            "set -e; echo AGS-BASELINE-OK; python3 -c 'print(2**10)'; "
            "cat /etc/os-release | grep -E '^(NAME|VERSION)='; "
            "nproc; free -m | head -2; df -h / | tail -1",
            user="root",
            timeout=60,
        )
        case.check("数据面执行 shell 命令", code == 0 and "AGS-BASELINE-OK" in out,
                   f"exit={code}", f"exit={code}, stderr={err[:200]}",
                   evidence={"exit_code": code, "stdout": out, "stderr": err})
    except Exception as exc:  # noqa: BLE001
        case.fail("数据面执行 shell 命令", str(exc)[:400])
    case.attach("shell-output", f"{out}\n--- stderr ---\n{err}")

    # ---- 步骤 6: 文件 API ----
    try:
        sbx.files.write("/tmp/baseline.txt", "baseline-payload")
        content = sbx.files.read("/tmp/baseline.txt")
        case.check("文件 API 读写", content == "baseline-payload",
                   "写入后读回一致", f"内容不一致: {content!r}")
    except Exception as exc:  # noqa: BLE001
        case.fail("文件 API 读写", str(exc)[:300])

    # ---- 步骤 7: 网络连通性（按模式区分预期）----
    try:
        if net_label == "VPC":
            code, out, err = E2B.run(
                sbx, "timeout 8 curl -sS -o /dev/null -w '%{http_code}' https://www.tencentcloud.com 2>&1 || echo NO-EGRESS",
                user="root", timeout=30)
            case.ok("VPC 出网行为记录", f"结果={out.strip()}", evidence={"exit": code, "out": out, "err": err})
            case.note("VPC 模式通常无公网出口（除非子网挂 NAT）；该步骤只记录行为，不作断言")
        else:
            code, out, err = E2B.run(
                sbx, "timeout 8 curl -sS -o /dev/null -w '%{http_code}' https://www.tencentcloud.com",
                user="root", timeout=30)
            case.check("PUBLIC 模式可出网", out.strip().startswith("2"), f"HTTP {out.strip()}",
                       f"HTTP {out.strip()}, err={err[:150]}")
    except Exception as exc:  # noqa: BLE001
        case.fail("网络连通性检查", str(exc)[:300])

    # ---- 步骤 8: 停止实例并确认回收 ----
    t0 = time.time()
    try:
        if sbx is not None:
            E2B.kill(sbx)
        ags.stop_instance(instance_id)
        gone = ags.wait_instance_gone(instance_id, timeout=180)
        case.check("停止实例并确认回收", gone, "实例已进入终态", "等待超时，实例可能仍在运行",
                   evidence={"duration": time.time() - t0})
    except Exception as exc:  # noqa: BLE001
        case.fail("停止实例并确认回收", str(exc)[:300])

    rec.write(Path(f"reports/TC-01-{net_label}.md"))
    rec.write_case_docs(Path("testcases"))
    return 0 if case.status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
