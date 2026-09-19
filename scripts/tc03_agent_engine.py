#!/usr/bin/env python3
"""TC-03 Agent Engine（弹性部署 Deployment）测试。

重要地域约束（已实测）：
  - Deployment API 仅支持 ap-shanghai / ap-hongkong（文档另列 ap-chongqing）。
    ap-beijing / ap-guangzhou / ap-singapore 返回 UnsupportedRegion。
  - 绑定工具必须 Persistent=true，且 Persistent 只支持 custom / mobile /
    android-world / osworld / waa 类型（code-interpreter 会被拒）。
  - 数据面域名格式：https://{port}-{deploymentId}.{region}.tencentags.com
    （不是 .agents.tencentags.com）

覆盖用例：
  TC-03-1 地域支持性探测（记录哪些地域可用）
  TC-03-2 创建 Persistent 工具（负例：code-interpreter 应被拒）
  TC-03-3 创建 Deployment → ACTIVE
  TC-03-4 AcquireDeploymentToken 并访问数据面
  TC-03-5 修改伸缩配置（ModifyDeployment 全量替换语义）
  TC-03-6 查询列表 / 单查
  TC-03-7 异步删除
  TC-03-8 负例：绑定非 Persistent 工具应被拒

用法：
    AGS_TARGET_REGION=ap-shanghai python3 scripts/tc03_agent_engine.py
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib import CFG, AgsApi, CleanupRegistry, Recorder  # noqa: E402

REGION = os.environ.get("AGS_TARGET_REGION", "ap-shanghai")
# 已验证可用：cookbook 的 httpbin 镜像，容器内 8080 提供 HTTP
IMAGE = os.environ.get("AGT_HTTPBIN_IMAGE", "ccr.ccs.tencentyun.com/ags.dev/go-httpbin:v2.25.0")
PROBE = {
    "HttpGet": {"Path": "/status/200", "Port": 8080, "Scheme": "HTTP"},
    "ReadyTimeoutMs": 30000, "ProbeTimeoutMs": 1000, "ProbePeriodMs": 3000,
    "SuccessThreshold": 1, "FailureThreshold": 10,
}
HTTP_PATH = "/get"
DOMAIN_SUFFIX = "agents.tencentags.com"


def persistent_tool(ags: AgsApi, name: str, tool_type: str = "custom") -> dict:
    payload: dict = {
        "ToolName": name,
        "ToolType": tool_type,
        "Description": "TC-03 Agent Engine 测试工具",
        "NetworkConfiguration": {"NetworkMode": "PUBLIC"},
        "Persistent": True,
        "RoleArn": CFG.role_arn,
    }
    if tool_type == "custom":
        payload["CustomConfiguration"] = {
            "Image": IMAGE,
            "ImageRegistryType": "personal",
            "Command": ["/bin/go-httpbin"],
            "Args": ["-host", "0.0.0.0", "-port", "8080"],
            "Env": [{"Name": "EXCLUDE_HEADERS", "Value": "X-Access-Token"}],
            "Ports": [{"Name": "http", "Port": 8080, "Protocol": "TCP"}],
            "Resources": {"CPU": "200m", "Memory": "500Mi"},
            "Probe": PROBE,
        }
    return payload


def main() -> int:
    rec = Recorder(f"TC-03 Agent Engine 弹性部署（region={REGION}）")
    ags = AgsApi(region=REGION)
    cleanup = CleanupRegistry(keep=CFG.keep_resources)
    ts = int(time.time())
    tool_name = f"{CFG.run_prefix}-tc03-{ts}"
    tool_id = None
    dpl_id = None

    # ============ TC-03-1 地域支持性探测 ============
    case1 = rec.case(
        "TC-03-1", "Deployment 接口地域支持性探测",
        purpose="确认 Deployment 系列接口在哪些地域可用。文档声明仅 ap-chongqing / ap-hongkong / ap-shanghai。",
        prereq="腾讯云凭据可用",
    )
    region_result: dict[str, str] = {}
    for region in ["ap-shanghai", "ap-hongkong", "ap-chongqing", "ap-beijing", "ap-guangzhou", "ap-singapore"]:
        try:
            AgsApi(region=region).describe_deployments({"Limit": 5})
            region_result[region] = "SUPPORTED"
        except Exception as exc:  # noqa: BLE001
            msg = str(exc)
            region_result[region] = "UNSUPPORTED" if "UnsupportedRegion" in msg else f"ERROR: {msg[:80]}"
    case1.ok("地域探测完成", f"{REGION} 为目标地域", evidence=region_result)
    case1.check("目标地域可用", region_result.get(REGION) == "SUPPORTED",
                f"{REGION} 支持 Deployment", f"{REGION} 不支持: {region_result.get(REGION)}")
    case1.check("北京地域不支持（预期行为，记录用）", region_result.get("ap-beijing") == "UNSUPPORTED",
                "ap-beijing 返回 UnsupportedRegion", f"ap-beijing 实际: {region_result.get('ap-beijing')}")

    # ============ TC-03-2 创建 Persistent 工具 ============
    case2 = rec.case(
        "TC-03-2", "创建 Persistent 工具（含类型约束负例）",
        purpose="Deployment 必须绑定 Persistent=true 的工具；验证 Persistent 的类型限制：仅 custom/mobile/android-world/osworld/waa 支持，code-interpreter 应被拒。",
        prereq=f"镜像 {IMAGE} 在 {REGION} 可拉取",
    )
    try:
        bad = persistent_tool(ags, f"{CFG.run_prefix}-tc03-badtype-{ts}", tool_type="code-interpreter")
        ags.create_tool(bad)
        case2.fail("负例：code-interpreter + Persistent", "预期被拒但创建成功了")
    except Exception as exc:  # noqa: BLE001
        msg = str(exc)
        case2.check("code-interpreter 不支持 Persistent", "persistent mode is only supported" in msg or "InvalidParameter" in msg,
                    "拒绝符合预期", f"错误不符: {msg[:200]}", evidence=msg[:800])
    try:
        resp = ags.create_tool(persistent_tool(ags, tool_name))
        tool_id = resp.get("ToolId")
        cleanup.tool(ags, tool_id)
        case2.ok("创建 custom Persistent 工具", f"ToolId={tool_id}", evidence=resp)
        tool = ags.wait_tool(tool_id, want="ACTIVE", timeout=600)
        case2.check("工具 Persistent=true", bool(tool.get("Persistent")),
                    f"Persistent={tool.get('Persistent')}", "Persistent 非 true",
                    evidence={"Status": tool.get("Status"), "Persistent": tool.get("Persistent")})
    except Exception as exc:  # noqa: BLE001
        case2.fail("创建 custom Persistent 工具", str(exc)[:500])
        rec.write(Path("reports/TC-03.md"))
        return 1

    # ============ TC-03-3 创建 Deployment ============
    case3 = rec.case(
        "TC-03-3", "创建 Deployment 并等待 ACTIVE",
        purpose="绑定 Persistent 工具创建弹性部署，验证默认值物化（伸缩 / 生命周期 / 亲和）。",
        prereq=f"工具 {tool_name} 已 ACTIVE 且 Persistent=true",
    )
    dpl_name = f"{CFG.run_prefix}-dpl-{ts}"
    create_payload = {
        "DeploymentName": dpl_name,
        "ToolId": tool_id,
        "ScalingConfiguration": {"MinInstanceCount": 0, "MaxInstanceCount": 3,
                                 "MaxInstanceRequestConcurrency": 10},
        "LifecycleConfiguration": {"IdleTimeoutSeconds": 300, "IdleAction": "STOP"},
        "AffinityConfiguration": {"Mode": "BEST_EFFORT"},
    }
    case3.attach_json("create-deployment-request", create_payload)
    try:
        resp = ags.create_deployment(create_payload)
        d = resp.get("Deployment", {})
        dpl_id = d.get("DeploymentId")
        cleanup.deployment(ags, dpl_id)
        case3.ok("CreateDeployment", f"DeploymentId={dpl_id}", evidence=resp)
        case3.check("状态为 ACTIVE", d.get("Status") == "ACTIVE",
                    f"Status={d.get('Status')}", f"Status={d.get('Status')}")
        sc = d.get("ScalingConfiguration") or {}
        case3.check("伸缩配置已物化", sc.get("MaxInstanceCount") is not None,
                    f"Scaling={sc}", "未返回伸缩配置")
        lc = d.get("LifecycleConfiguration") or {}
        case3.check("生命周期配置已物化", lc.get("IdleAction") in ("STOP", "PAUSE"),
                    f"IdleAction={lc.get('IdleAction')}", f"IdleAction={lc.get('IdleAction')}")
        af = d.get("AffinityConfiguration") or {}
        case3.check("亲和配置含 HeaderName", bool(af.get("HeaderName")),
                    f"HeaderName={af.get('HeaderName')}", "缺少 HeaderName")
    except Exception as exc:  # noqa: BLE001
        case3.fail("CreateDeployment", str(exc)[:500])
        rec.write(Path("reports/TC-03.md"))
        return 1

    # ============ TC-03-4 获取 Token 并访问数据面 ============
    case4 = rec.case(
        "TC-03-4", "获取 Deployment Token 并访问数据面",
        purpose=f"通过 AcquireDeploymentToken 拿短期 Token，携带 X-Access-Token 访问 https://8080-{{dpl}}. {REGION}.tencentags.com，验证稳定入口按需拉起沙箱并返回内容。",
        prereq=f"Deployment {dpl_id} 为 ACTIVE；工具容器在 8080 监听 HTTP",
    )
    try:
        tok_resp = ags.acquire_deployment_token(dpl_id)
        token = tok_resp.get("Token")
        case4.ok("AcquireDeploymentToken", f"Token 前缀={str(token)[:12]}… ExpiresAt={tok_resp.get('ExpiresAt')}",
                 evidence={k: v for k, v in tok_resp.items() if k != "RequestId"})
    except Exception as exc:  # noqa: BLE001
        case4.fail("AcquireDeploymentToken", str(exc)[:400])
        token = None

    if token:
        import requests  # noqa: PLC0415

        url = f"https://8080-{dpl_id}.{REGION}.{DOMAIN_SUFFIX}"
        case4.note(f"数据面 URL: {url}（HTTP 端口域名规则：{{port}}-{{dpl-id}}.{{region}}.agents.{{data-plane-domain}}）")
        ok = False
        last = ""
        last_body = ""
        deadline = time.time() + 240
        attempts = 0
        while time.time() < deadline:
            attempts += 1
            try:
                tok = ags.acquire_deployment_token(dpl_id).get("Token")
                r = requests.get(url + HTTP_PATH, headers={"X-Access-Token": tok}, timeout=25)
                last = f"HTTP {r.status_code}"
                last_body = r.text[:400]
                print(f"    [TC-03-4] attempt {attempts}: {last} {last_body[:120]!r}")
                if r.status_code == 200:
                    ok = True
                    break
            except Exception as exc:  # noqa: BLE001
                last = f"ERR {str(exc)[:150]}"
                print(f"    [TC-03-4] attempt {attempts}: {last}")
            time.sleep(10)
        case4.check("数据面返回 200", ok, f"HTTP 200（尝试 {attempts} 次）",
                    f"未成功（尝试 {attempts} 次）：{last}",
                    evidence={"url": url, "attempts": attempts, "last": last, "body": last_body})
        if ok:
            case4.check("响应为预期的 httpbin JSON 结构", '"headers"' in last_body or "args" in last_body,
                        "返回 httpbin 标准结构", f"响应体不符: {last_body[:200]}",
                        evidence=last_body)
        # 验证 Token 是必需的
        try:
            r2 = requests.get(url + HTTP_PATH, timeout=20)
            case4.check("缺少 X-Access-Token 时应被拒绝", r2.status_code != 200,
                        "无 Token 被拒", f"无 Token 竟然也返回 {r2.status_code}",
                        evidence={"status": r2.status_code, "body": r2.text[:200]})
        except Exception as exc:  # noqa: BLE001
            case4.ok("缺少 X-Access-Token 时连接被拒", str(exc)[:150])

    # ============ TC-03-4b 验证按需拉起实例 ============
    case4b = rec.case(
        "TC-03-4b", "弹性部署按需拉起沙箱实例",
        purpose="数据面首次请求应触发平台自动创建沙箱实例（MinInstanceCount=0 时的 0→N 扩容），验证工具下有 RUNNING 实例。",
        prereq=f"Deployment {dpl_id} 绑定的工具 {tool_id}",
    )
    try:
        insts = ags.describe_instances({"Limit": 100}).get("InstanceSet", [])
        mine = [i for i in insts if i.get("ToolId") == tool_id]
        running = [i for i in mine if i.get("Status") in ("RUNNING", "PAUSED")]
        case4b.check("存在由部署拉起的实例", bool(running),
                     f"{len(running)} 个实例: {[i['InstanceId'] for i in running]}",
                     "未发现实例（部署可能未真正转发请求）",
                     evidence=[{"InstanceId": i["InstanceId"], "Status": i["Status"]} for i in mine])
        for i in mine:
            cleanup.instance(ags, i["InstanceId"])
    except Exception as exc:  # noqa: BLE001
        case4b.fail("检查部署拉起实例", str(exc)[:400])

    # ============ TC-03-5 修改伸缩配置 ============
    case5 = rec.case(
        "TC-03-5", "ModifyDeployment 修改伸缩与生命周期配置",
        purpose="验证修改配置后回读一致。注意：伸缩/生命周期/亲和对象是「完整替换」语义，必须提供该对象的全部字段。",
        prereq=f"Deployment {dpl_id} 为 ACTIVE",
    )
    try:
        new_sc = {"MinInstanceCount": 1, "MaxInstanceCount": 5, "MaxInstanceRequestConcurrency": 20}
        new_lc = {"IdleTimeoutSeconds": 600, "IdleAction": "PAUSE"}
        resp = ags.modify_deployment({
            "DeploymentId": dpl_id,
            "ScalingConfiguration": new_sc,
            "LifecycleConfiguration": new_lc,
        })
        case5.ok("ModifyDeployment 调用成功", evidence=resp)
        time.sleep(3)
        d = ags.describe_deployment(dpl_id).get("Deployment", {})
        sc = d.get("ScalingConfiguration") or {}
        lc = d.get("LifecycleConfiguration") or {}
        case5.check("伸缩配置已更新", sc.get("MinInstanceCount") == 1 and sc.get("MaxInstanceCount") == 5,
                    f"Scaling={sc}", f"未生效: {sc}")
        case5.check("生命周期配置已更新", lc.get("IdleAction") == "PAUSE",
                    f"IdleAction={lc.get('IdleAction')}", f"未生效: {lc}")
    except Exception as exc:  # noqa: BLE001
        case5.fail("ModifyDeployment", str(exc)[:500])

    # ============ TC-03-6 查询列表 / 单查 ============
    case6 = rec.case(
        "TC-03-6", "DescribeDeployment / DescribeDeploymentList 查询",
        purpose="验证按 ID 单查与列表查询都能命中刚创建的 Deployment。",
        prereq=f"Deployment {dpl_id} 存在",
    )
    try:
        one = ags.describe_deployment(dpl_id).get("Deployment", {})
        case6.check("DescribeDeployment 命中", one.get("DeploymentId") == dpl_id,
                    f"Name={one.get('DeploymentName')}", "未命中", evidence=one)
        lst = ags.describe_deployments({"Limit": 50}).get("DeploymentSet", [])
        ids = [x.get("DeploymentId") for x in lst]
        case6.check("DescribeDeploymentList 命中", dpl_id in ids,
                    f"列表共 {len(lst)} 条", f"列表中找不到 {dpl_id}", evidence=ids)
    except Exception as exc:  # noqa: BLE001
        case6.fail("查询 Deployment", str(exc)[:400])

    # ============ TC-03-7 负例：非 Persistent 工具 ============
    case7 = rec.case(
        "TC-03-7", "负例：绑定非 Persistent 工具应被拒",
        purpose="文档要求绑定的工具必须 Persistent=true。用已有非 Persistent 工具（如 code-interpreter）创建 Deployment 应报错。",
        prereq="存在非 Persistent 的工具",
    )
    try:
        tools = ags.describe_tools({"Limit": 50}).get("SandboxToolSet", [])
        nonpersist = next((t for t in tools if not t.get("Persistent")), None)
        if nonpersist is None:
            case7.skip("找不到非 Persistent 工具", "跳过该负例")
        else:
            ags.create_deployment({"DeploymentName": f"{CFG.run_prefix}-bad-{ts}",
                                   "ToolId": nonpersist["ToolId"]})
            case7.fail("绑定非 Persistent 工具", f"预期被拒，但用 {nonpersist['ToolName']} 创建成功了")
    except Exception as exc:  # noqa: BLE001
        msg = str(exc)
        case7.check("非 Persistent 工具被拒", "InvalidParameter" in msg or "Persistent" in msg or "persistent" in msg,
                    "拒绝符合预期", f"错误不符: {msg[:200]}", evidence=msg[:800])

    # ============ TC-03-8 异步删除 ============
    case8 = rec.case(
        "TC-03-8", "删除 Deployment（异步）+ 同名资源占用",
        purpose="验证删除是异步操作、需轮询最终状态；删除后同名才可复用。",
        prereq=f"Deployment {dpl_id} 存在",
    )
    try:
        resp = ags.delete_deployment(dpl_id)
        case8.ok("DeleteDeployment 调用成功", evidence=resp)
        final = None
        deadline = time.time() + 180
        while time.time() < deadline:
            try:
                d = ags.describe_deployment(dpl_id).get("Deployment", {})
                st = d.get("Status")
                if st in (None, "") or st == "DELETED":
                    final = "GONE"
                    break
                final = st
            except Exception:  # noqa: BLE001 - 资源消失后的查询报错也算成功
                final = "GONE"
                break
            time.sleep(5)
        case8.check("删除最终生效", final == "GONE", "资源已不可查/已删除", f"仍处于 {final}",
                    evidence={"final": final})
        cleanup.forget(dpl_id)  # Deployment 已删除，避免重复清理
    except Exception as exc:  # noqa: BLE001
        case8.fail("DeleteDeployment", str(exc)[:400])

    rec.write(Path("reports/TC-03.md"))
    rec.write_case_docs(Path("testcases"))
    return 0 if all(c.status == "PASS" for c in rec.cases) else 1


if __name__ == "__main__":
    raise SystemExit(main())
