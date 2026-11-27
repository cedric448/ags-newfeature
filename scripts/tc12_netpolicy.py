#!/usr/bin/env python3
"""TC-12 AGS 网络代理 + NetworkPolicy 测试。

场景：
  1. 创建 VPC 网络类型 Tool（子网与测试机同子网，可访问本机代理）
  2. 沙箱内经本机内网 IP 的代理出网（出口香港）
  3. 创建沙箱时 x-network-policy=deny-all 禁网，执行完 PATCH 为 allow-all 联网

关键结论（2026-11-27 实测，ap-beijing，账号已完成 NetworkPolicy 白名单）：
  - VPC 工具必须选用与本机相同的子网，否则 NetworkConnector 隔离导致不可达
  - **NetworkPolicy 启用后，沙箱进程内的 `curl -x 代理` 不再可用**：zeroproxy sidecar
    通过 iptables 拦截全部 TCP，外部代理请求会被改写，返回 400/502
  - 正确做法：用 `Decision=upstream` + `UpstreamConfig.ForwardProxy=true` 把流量
    交给本机代理转发。缺少 ForwardProxy 时上游收到的是原始 TLS 字节，代理无法识别
    （会返回 400 / 502 / 500）
  - deny-all 返回 403 `No policy rule matched the request`
  - PATCH 为 allow-all 后约 10s 内生效，https 恢复 204，出口为香港

用法：
    python3 scripts/tc12_netpolicy.py
    python3 scripts/tc12_netpolicy.py --probe-only   # 只验证代理链路
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib import CFG, AgsApi, E2B, ensure_domain  # noqa: E402

ENVD_CMD = "/usr/bin/envd -port 49983"

C_HTTPS = ("timeout 20 curl -s -o /dev/null --write-out '%{http_code}' "
           "https://www.gstatic.com/generate_204")  # noqa: E501
C_IPINFO = "timeout 20 curl -s https://ipinfo.io/json | tr -d '\\n' | head -c 200"


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


def policy_deny():
    return {"DefaultDecision": "deny", "Rules": []}


def policy_allow_via_proxy(proxy_ip, proxy_port):
    """allow-all，并把出网流量交给本机代理转发。

    ForwardProxy=true 是必要条件：开启后才按 HTTP forward proxy 语义转发
    （HTTP absolute-form / HTTPS CONNECT 隧道），否则上游收到原始 TLS 字节无法处理。
    """
    return {
        "DefaultDecision": "allow",
        "Rules": [{
            "Name": "forward-all-via-local-proxy",
            "Decision": "upstream",
            "Resources": [{"Hosts": ["*"]}],
            "UpstreamConfig": {
                "Host": proxy_ip, "Scheme": "http", "Port": proxy_port,
                "ForwardProxy": True,
            },
        }],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--proxy-ip", default="172.21.80.142")
    ap.add_argument("--proxy-port", type=int, default=1087)
    ap.add_argument("--subnet", default="subnet-heh2tv3n")
    ap.add_argument("--sg", default="sg-p3sxc9y3")
    ap.add_argument("--probe-only", action="store_true")
    args = ap.parse_args()

    ensure_domain()
    from e2b import Sandbox  # noqa: PLC0415

    ags = AgsApi()
    checks = []

    def add(name, ok, detail=""):
        checks.append({"name": name, "pass": bool(ok), "detail": str(detail)[:140]})
        print("  %-44s %s  %s" % (name, "PASS" if ok else "FAIL", str(detail)[:80]))
        sys.stdout.flush()

    def run_code(sb, cmd):
        try:
            return sb.commands.run(cmd, user="root", timeout=90).stdout.strip()
        except Exception:  # noqa: BLE001
            return ""

    print("=== TC-12 AGS 网络代理 + NetworkPolicy ===")
    print("region=%s proxy=%s:%d" % (ags.region, args.proxy_ip, args.proxy_port))
    print()

    # ---- 1. VPC 工具 ----
    print("[1] 创建 VPC 网络类型 Tool")
    name = "%s-np-%d" % (CFG.run_prefix, int(time.time()))
    try:
        tid = ags.create_tool(build_tool(name, args.subnet, args.sg))["ToolId"]
        ags.wait_tool(tid, want="ACTIVE", timeout=900)
        nc = (ags.get_tool(tid) or {}).get("NetworkConfiguration") or {}
        print("  ToolId=%s NetworkMode=%s" % (tid, nc.get("NetworkMode")))
        print("  VpcConfig=%s" % json.dumps(nc.get("VpcConfig"), ensure_ascii=False))
        add("VPC Tool 创建成功", nc.get("NetworkMode") == "VPC", tid)
    except Exception as exc:  # noqa: BLE001
        add("VPC Tool 创建成功", False, str(exc)[:150])
        return 1

    # ---- 2. 无策略基线下验证代理链路 ----
    print()
    print("[2] 基线：无 NetworkPolicy 时经本机代理出网")
    r = ags.call("StartSandboxInstance", {"ToolId": tid, "Timeout": "30m"})
    iid = (r.get("Instance") or {}).get("InstanceId") or r.get("InstanceId")
    ags.wait_instance(iid, want="RUNNING", timeout=900)
    print("  InstanceId=%s" % iid)
    sbx = Sandbox.connect(iid)

    tcp = run_code(sbx, "timeout 6 bash -c '</dev/tcp/%s/%d' 2>&1 && echo OK || echo FAIL"
                        % (args.proxy_ip, args.proxy_port))
    add("沙箱可连通本机代理端口", tcp.endswith("OK"), "%s:%d" % (args.proxy_ip, args.proxy_port))

    code = run_code(sbx, "timeout 20 curl -s -o /dev/null --write-out '%%{http_code}' "
                         "-x http://%s:%d http://www.gstatic.com/generate_204"
                         % (args.proxy_ip, args.proxy_port))
    add("基线经代理出网成功", code == "204", code)

    info = run_code(sbx, "timeout 20 curl -s -x http://%s:%d https://ipinfo.io/json"
                         % (args.proxy_ip, args.proxy_port))
    add("基线代理出口为香港", "Hong Kong" in info,
        (info.split('"ip"')[-1][:46] if info else "(empty)"))

    direct = run_code(sbx, "timeout 12 curl -s -o /dev/null --write-out '%%{http_code}' "
                           "http://www.baidu.com")
    add("基线直连公网不可达", direct in ("", "000"), direct or "(timeout)")

    if args.probe_only:
        try:
            ags.stop_instance(iid)
        except Exception:  # noqa: BLE001
            pass
        return 0 if all(c["pass"] for c in checks) else 1

    # ---- 3. deny-all 创建 ----
    print()
    print("[3] 创建沙箱时 x-network-policy = deny-all（禁网）")
    deny = policy_deny()
    sb = E2B.create(name, timeout=1800, metadata={
        "owner": "tc12",
        "x-network-policy": json.dumps(deny, separators=(",", ":")),
    })
    sid = sb.sandbox_id
    print("  sandbox=%s" % sid)
    np_read = (ags.get_instance(sid) or {}).get("NetworkPolicy")
    print("  NetworkPolicy 回读=%s" % json.dumps(np_read, ensure_ascii=False))
    add("创建时 deny-all 已下发", (np_read or {}).get("DefaultDecision") == "deny",
        json.dumps(np_read, ensure_ascii=False))
    time.sleep(10)

    d1 = run_code(sb, C_HTTPS)
    d2 = run_code(sb, C_IPINFO)
    blocked = d1 == "403" and "Request denied" in d2
    add("deny-all 下 HTTPS 出网被阻断", d1 == "403", d1)
    add("deny-all 返回 No policy rule matched", "No policy rule matched" in d2,
        d2[:70] if d2 else "(empty)")

    # ---- 4. PATCH 为 allow-all ----
    print()
    print("[4] PATCH -> allow-all（经本机代理转发）")
    allow = policy_allow_via_proxy(args.proxy_ip, args.proxy_port)
    ags.call("UpdateSandboxInstance", {"InstanceId": sid, "NetworkPolicy": allow})
    print("  UpdateSandboxInstance 已提交")

    ok = False
    waited = 0
    for _ in range(9):
        time.sleep(10)
        waited += 10
        c = run_code(sb, "timeout 15 curl -s -o /dev/null "
                         "--write-out '%{http_code}' https://www.gstatic.com/generate_204")
        np_now = (ags.get_instance(sid) or {}).get("NetworkPolicy")
        print("    t+%ds NP.DefaultDecision=%s https=%s" % (
            waited, (np_now or {}).get("DefaultDecision"), c))
        if c == "204":
            ok = True
            break
    add("PATCH 为 allow-all 后 HTTPS 恢复", ok, "%d s 生效" % waited if ok else "超时")

    a1 = run_code(sb, "timeout 20 curl -s -o /dev/null --write-out '%{http_code}' http://example.com")
    add("allow-all 下 HTTP 出网成功", a1 == "200", a1)

    a2 = run_code(sb, C_IPINFO)
    add("allow-all 后代理出口为香港", "Hong Kong" in a2,
        (a2.split('"ip"')[-1][:46] if a2 else "(empty)"))

    # ---- 汇总 ----
    passed = sum(1 for c in checks if c["pass"])
    print()
    print("=" * 80)
    print("结论：%d/%d 检查点通过" % (passed, len(checks)))
    print("=" * 80)

    out = Path("reports/artifacts/tc12-netpolicy.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "params": vars(args), "tool_id": tid, "instance_id": iid, "sandbox_id": sid,
        "deny_policy": deny, "allow_policy": allow,
        "checks": checks, "summary": {"pass": passed, "total": len(checks)},
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print("明细已写入 %s" % out)

    for x in (iid, sid):
        try:
            ags.stop_instance(x)
        except Exception:  # noqa: BLE001
            pass
    return 0 if passed == len(checks) else 1


if __name__ == "__main__":
    sys.exit(main())
