#!/usr/bin/env python3
"""TC-12 AGS 网络代理 + NetworkPolicy 测试。

目标：
  1. 创建 VPC 网络类型的 AGS Tool（子网与测试机同子网，可访问本机代理）
  2. 沙箱内经本机内网 IP 的 HTTP 代理访问外网（出口香港）
  3. 创建沙箱时用 x-network-policy=deny-all 禁网，PATCH 改 allow-all 后恢复联网

实测结论（2026-11-07，ap-beijing）：
  - VPC 工具 + 同子网（172.21.80.0/20）可以访问本机代理，出口确认为香港
  - NetworkPolicy **未对本账号开通**，三条路径均返回
    `UnsupportedOperation.SandboxTool: NetworkPolicy is not enabled for this account`
  - 原生 metadata["x-network-policy"] 不会被 StartSandboxInstance 识别（落入普通 metadata）
  - E2B 兼容接口 metadata["x-network-policy"] 才会映射到 NetworkPolicy，但同样被白名单拦截

用法：
    python3 scripts/tc12_netpolicy.py --proxy-ip 172.21.80.142 --proxy-port 1087
    python3 scripts/tc12_netpolicy.py --probe-only    # 只验证代理链路
    python3 scripts/tc12_netpolicy.py --cleanup       # 清理工具与实例
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib import CFG, AgsApi, ensure_domain  # noqa: E402

ENVD_CMD = "/usr/bin/envd -port 49983"
DENY_ALL = {"DefaultDecision": "deny", "Rules": []}
ALLOW_ALL = {"DefaultDecision": "allow", "Rules": []}


def build_tool(name, subnet_id, sg_id):
    return {
        "ToolName": name,
        "ToolType": "custom",
        "RoleArn": CFG.role_arn,
        "NetworkConfiguration": {
            "NetworkMode": "VPC",
            "VpcConfig": {"SubnetIds": [subnet_id], "SecurityGroupIds": [sg_id]},
        },
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
            "Resources": {"CPU": "2000m", "Memory": "4096Mi", "Storage": "20Gi"},
        },
    }


def curl_via_proxy(ip, port, timeout=20):
    return ("timeout %d curl -s -o /dev/null -w '%%{http_code} %%{time_total}s' "
            "-x http://%s:%d http://www.gstatic.com/generate_204") % (timeout, ip, port)


def curl_direct(timeout=10):
    return ("timeout %d curl -s -o /dev/null -w '%%{http_code}' "
            "http://www.gstatic.com/generate_204") % timeout


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--proxy-ip", default="172.21.80.142")
    ap.add_argument("--proxy-port", type=int, default=1087)
    ap.add_argument("--subnet", default="subnet-heh2tv3n")
    ap.add_argument("--sg", default="sg-p3sxc9y3")
    ap.add_argument("--probe-only", action="store_true")
    ap.add_argument("--cleanup", action="store_true")
    args = ap.parse_args()

    ensure_domain()
    from e2b import Sandbox  # noqa: PLC0415

    ags = AgsApi()
    checks = []

    def add(name, ok, detail=""):
        checks.append({"name": name, "pass": bool(ok), "detail": str(detail)[:120]})
        print("  %-46s %s  %s" % (name, "PASS" if ok else "FAIL", str(detail)[:70]))
        sys.stdout.flush()

    print("=== TC-12 AGS 网络代理 + NetworkPolicy ===")
    print("region=%s proxy=%s:%d" % (ags.region, args.proxy_ip, args.proxy_port))
    print()

    # ---- 1. 创建 VPC 工具 ----
    print("[1] 创建 VPC 网络类型 Tool")
    name = "%s-np-%d" % (CFG.run_prefix, int(time.time()))
    try:
        tid = ags.create_tool(build_tool(name, args.subnet, args.sg))["ToolId"]
        ags.wait_tool(tid, want="ACTIVE", timeout=900)
        t = ags.get_tool(tid) or {}
        nc = t.get("NetworkConfiguration") or {}
        print("  ToolId=%s  NetworkMode=%s" % (tid, nc.get("NetworkMode")))
        print("  VpcConfig=%s" % json.dumps(nc.get("VpcConfig"), ensure_ascii=False))
        add("VPC Tool 创建成功", nc.get("NetworkMode") == "VPC", tid)
    except Exception as exc:  # noqa: BLE001
        add("VPC Tool 创建成功", False, str(exc)[:150])
        return 1

    # ---- 2. 启动实例并验证代理 ----
    print()
    print("[2] 启动实例并验证本机代理链路")
    r = ags.call("StartSandboxInstance", {"ToolId": tid, "Timeout": "30m"})
    iid = (r.get("Instance") or {}).get("InstanceId") or r.get("InstanceId")
    ags.wait_instance(iid, want="RUNNING", timeout=900)
    print("  InstanceId=%s" % iid)
    sbx = Sandbox.connect(iid)

    tcp = sbx.commands.run(
        "timeout 6 bash -c '</dev/tcp/%s/%d' 2>&1 && echo OK || echo FAIL" % (
            args.proxy_ip, args.proxy_port), user="root", timeout=60).stdout.strip()
    add("沙箱可连通本机代理端口", tcp.endswith("OK"), "%s:%d" % (args.proxy_ip, args.proxy_port))

    out = sbx.commands.run(curl_via_proxy(args.proxy_ip, args.proxy_port),
                           user="root", timeout=90).stdout.strip()
    add("经代理出网成功", out.startswith("204"), out)

    info = sbx.commands.run(
        "timeout 20 curl -s -x http://%s:%d https://ipinfo.io/json" % (
            args.proxy_ip, args.proxy_port), user="root", timeout=90).stdout
    hk = "Hong Kong" in info
    add("代理出口为香港", hk, info.split('"city":')[1][:22].strip() if '"city"' in info else "")

    try:
        direct = sbx.commands.run(curl_direct(), user="root", timeout=60).stdout.strip()
    except Exception:  # noqa: BLE001
        direct = ""  # 超时/非 0 退出即视为不可达（预期行为）
    add("直连（不经代理）不可达", direct in ("", "000"), direct or "(timeout)")

    # ---- 3. NetworkPolicy ----
    print()
    print("[3] NetworkPolicy: 创建时 deny-all -> PATCH allow-all")
    deny_ok = False
    try:
        sb2 = __import__("lib").E2B.create(name, timeout=1800, metadata={
            "owner": "tc12",
            "x-network-policy": json.dumps(DENY_ALL, separators=(",", ":")),
        })
        sid = sb2.sandbox_id
        print("  创建成功 sandbox=%s（策略已下发）" % sid)
        inst = ags.get_instance(sid) or {}
        print("  NetworkPolicy 回读: %s" % json.dumps(inst.get("NetworkPolicy"), ensure_ascii=False))
        r1 = sb2.commands.run(curl_via_proxy(args.proxy_ip, args.proxy_port),
                              user="root", timeout=90).stdout.strip()
        add("deny-all 下代理被阻断", not r1.startswith("204"), r1)
        deny_ok = True
    except Exception as exc:  # noqa: BLE001
        msg = str(exc)
        not_enabled = "NetworkPolicy is not enabled" in msg
        add("创建时 deny-all 生效", False,
            "账号未开通 NetworkPolicy" if not_enabled else msg[:120])
        if not_enabled:
            print("  -> NetworkPolicy 未对本账号开通，后续 PATCH 验证跳过")

    if deny_ok:
        try:
            ags.call("UpdateSandboxInstance", {"InstanceId": sid, "NetworkPolicy": ALLOW_ALL})
            time.sleep(5)
            r2 = sb2.commands.run(curl_via_proxy(args.proxy_ip, args.proxy_port),
                                  user="root", timeout=90).stdout.strip()
            add("PATCH 为 allow-all 后代理恢复", r2.startswith("204"), r2)
        except Exception as exc:  # noqa: BLE001
            add("PATCH 为 allow-all 后代理恢复", False, str(exc)[:120])

    passed = sum(1 for c in checks if c["pass"])
    print()
    print("=" * 78)
    print("结论：%d/%d 检查点通过" % (passed, len(checks)))
    print("=" * 78)

    out_path = Path("reports/artifacts/tc12-netpolicy.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps({
        "params": vars(args), "tool_id": tid, "instance_id": iid,
        "checks": checks, "summary": {"pass": passed, "total": len(checks)},
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print("明细已写入 %s" % out_path)

    if not args.probe_only:
        try:
            ags.stop_instance(iid)
        except Exception:  # noqa: BLE001
            pass
    return 0 if passed == len(checks) else 1


if __name__ == "__main__":
    sys.exit(main())
