#!/usr/bin/env python3
"""TC-10 系统盘（Resources.Storage）真实生效验证。

目的：验证 CustomConfiguration.Resources.Storage 声明的系统盘大小，
      是否真的反映到沙箱内根分区 / 的实际容量上（而不是只在接口回显）。

关键前提：接口返回的 Storage 只是「声明值」（统一换算为 Mi），
          必须进入沙箱执行 df / findmnt 才能证明系统盘真实被拉起。

测试矩阵：
  E. 各档位遍历    —— 工具声明 1/20/50/100/150Gi，实例实际根分区是否一致
  B. 实例级覆盖    —— 工具声明 20Gi，启动时指定 50Gi，验证以 50Gi 为准
  C. 仅实例声明    —— 工具不声明，实例指定 30Gi
  D. 负例          —— 超上限 / 非档位 / 单位错误 / 缺 CPU

用法：
    python3 scripts/tc10_system_disk.py
    python3 scripts/tc10_system_disk.py --sizes 1,20,50
    python3 scripts/tc10_system_disk.py --keep
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib import CFG, AgsApi, CleanupRegistry, ensure_domain  # noqa: E402

ENVD_CMD = "/usr/bin/envd -port 49983"
DEFAULT_SIZES = ["1Gi", "20Gi", "50Gi", "100Gi", "150Gi"]


def build_payload(name, storage, cpu="2000m", memory="4096Mi"):
    res = {"CPU": cpu, "Memory": memory}
    if storage:
        res["Storage"] = storage
    return {
        "ToolName": name,
        "ToolType": "custom",
        "RoleArn": CFG.role_arn,
        "NetworkConfiguration": {"NetworkMode": "SANDBOX"},
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
            "Resources": res,
        },
    }


def to_gi(storage):
    """接口回显统一为 Mi，换算成 Gi 便于比对。"""
    if not storage:
        return None
    if storage.endswith("Mi"):
        return str(int(storage[:-2]) // 1024) + "Gi"
    return storage

def probe_rootfs(sbx):
    """进入沙箱，取根分区的真实容量。"""
    cmd = (
        "df -B1 / | tail -1; echo '::'; "
        "df -h / | tail -1; echo '::'; "
        "findmnt -no SOURCE,FSTYPE,SIZE / 2>/dev/null || true"
    )
    out = sbx.commands.run(cmd, user="root", timeout=90).stdout
    parts = [p.strip() for p in out.split("::")]
    res = {"raw": out.strip()}
    try:
        cols = parts[0].split()
        total_bytes = int(cols[1])
        res["total_bytes"] = total_bytes
        res["total_gib"] = round(total_bytes / 1024.0 ** 3, 2)
    except (IndexError, ValueError):
        res["total_gib"] = None
    res["df_h"] = parts[1].strip() if len(parts) > 1 else None
    res["findmnt"] = parts[2].strip() if len(parts) > 2 else None
    return res


def judge(declared_gi, actual_gib):
    """实测容量是否与声明一致。

    文件系统（ext4/overlay）元数据本身占用一部分，实测必然略小于声明值。
    小档位相对偏差更明显：1Gi 档实测约 973Mi，相对偏差约 5%。
    因此容差取 8%，并在结果中同时给出绝对偏差便于判断。
    """
    if actual_gib is None:
        return False, "无法读取根分区容量"
    diff = abs(actual_gib - declared_gi) / float(declared_gi)
    delta_mib = (actual_gib - declared_gi) * 1024
    detail = "偏差%.1f%%(%+.0fMiB)" % (diff * 100, delta_mib)
    if diff <= 0.08:
        return True, "一致 " + detail
    return False, "不一致（声明%dGi，实测%sGi，%s）" % (declared_gi, actual_gib, detail)


def run_case(ags, cleanup, tag, tool_storage, inst_storage):
    """一个场景：建工具 -> 起实例 -> 进沙箱量根分区 -> 回收。"""
    ts = int(time.time() * 1000) % 1000000
    name = "%s-disk-%s-%d" % (CFG.run_prefix, tag, ts)
    rec = {"case": tag, "tool_storage": tool_storage,
           "instance_storage": inst_storage}

    try:
        tool_id = ags.create_tool(build_payload(name, tool_storage))["ToolId"]
    except Exception as exc:
        rec["error"] = "建工具失败: " + str(exc)[:200]
        return rec
    cleanup.tool(ags, tool_id)

    try:
        tool = ags.wait_tool(tool_id, want="ACTIVE", timeout=900)
    except Exception as exc:
        rec["error"] = "工具未 ACTIVE: " + str(exc)[:160]
        return rec
    rec["tool_id"] = tool_id
    rec["tool_echo"] = to_gi(((tool.get("CustomConfiguration") or {})
                              .get("Resources") or {}).get("Storage"))

    payload = {"ToolId": tool_id, "Timeout": "30m"}
    if inst_storage:
        payload["CustomConfiguration"] = {
            "Resources": {"CPU": "2000m", "Memory": "4096Mi", "Storage": inst_storage}
        }
    try:
        resp = ags.call("StartSandboxInstance", payload)
        iid = (resp.get("Instance") or {}).get("InstanceId") or resp.get("InstanceId")
        cleanup.instance(ags, iid)
        ags.wait_instance(iid, want="RUNNING", timeout=900)
    except Exception as exc:
        rec["error"] = "启动失败: " + str(exc)[:200]
        return rec

    rec["instance_id"] = iid
    inst = ags.get_instance(iid) or {}
    rec["instance_echo"] = to_gi(((inst.get("CustomConfiguration") or {})
                                  .get("Resources") or {}).get("Storage"))

    from e2b import Sandbox

    try:
        sbx = Sandbox.connect(iid)
        rf = probe_rootfs(sbx)
        rec.update(rf)
        expected = inst_storage or tool_storage
        if expected:
            m = re.match(r"(\d+)Gi$", expected)
            if m:
                ok, why = judge(int(m.group(1)), rf.get("total_gib"))
                rec["expect_gi"] = int(m.group(1))
                rec["pass"] = ok
                rec["why"] = why
    except Exception as exc:
        rec["error"] = "进入沙箱失败: " + str(exc)[:160]
    finally:
        try:
            ags.stop_instance(iid)
        except Exception:
            pass
    return rec

def run_negative(ags, tag, storage, cpu):
    """负例：预期建工具被拒。"""
    name = "%s-diskneg-%s-%d" % (CFG.run_prefix, tag, int(time.time()))
    payload = build_payload(name, storage, cpu=cpu or "2000m")
    if cpu is None:
        payload["CustomConfiguration"]["Resources"].pop("CPU", None)
    try:
        r = ags.create_tool(payload)
        tid = r.get("ToolId")
        try:
            ags.delete_tool(tid)
        except Exception:
            pass
        return {"case": tag, "storage": storage, "expected": "reject",
                "result": "ACCEPTED", "pass": False, "detail": "本应拒绝却成功"}
    except Exception as exc:
        return {"case": tag, "storage": storage, "expected": "reject",
                "result": "REJECTED", "pass": True, "detail": str(exc)[:260]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sizes", default=",".join(DEFAULT_SIZES),
                    help="遍历档位，逗号分隔（默认 1,20,50,100,150Gi）")
    ap.add_argument("--keep", action="store_true")
    ap.add_argument("--skip-negative", action="store_true")
    args = ap.parse_args()

    sizes = [s.strip() for s in args.sizes.split(",") if s.strip()]
    ensure_domain()
    ags = AgsApi()
    cleanup = CleanupRegistry(keep=args.keep or CFG.keep_resources)

    print("=== TC-10 系统盘真实生效验证 ===")
    print("region=%s image=%s" % (ags.region, CFG.image))
    print("遍历档位: %s" % sizes)
    print("")

    results = []

    print("--- [E] 各档位：工具声明 -> 实例实际容量 ---")
    for size in sizes:
        r = run_case(ags, cleanup, "size" + size, size, None)
        results.append(r)
        mark = "PASS" if r.get("pass") else "FAIL"
        print("  %-7s 回显=%-8s 实测=%-8s [%s] %s" % (
            size, r.get("instance_echo"), str(r.get("total_gib")) + "Gi", mark,
            r.get("why") or r.get("error", "")))
        sys.stdout.flush()

    print("")
    print("--- [B] 实例级覆盖：工具 20Gi，启动时指定 50Gi ---")
    r = run_case(ags, cleanup, "override", "20Gi", "50Gi")
    results.append(r)
    print("  工具回显=%s 实例回显=%s 实测=%sGi [%s] %s" % (
        r.get("tool_echo"), r.get("instance_echo"), r.get("total_gib"),
        "PASS" if r.get("pass") else "FAIL", r.get("why") or r.get("error", "")))
    sys.stdout.flush()

    print("")
    print("--- [C] 工具未声明，实例指定 30Gi ---")
    r = run_case(ags, cleanup, "instonly", None, "30Gi")
    results.append(r)
    print("  工具回显=%s 实例回显=%s 实测=%sGi [%s] %s" % (
        r.get("tool_echo"), r.get("instance_echo"), r.get("total_gib"),
        "PASS" if r.get("pass") else "FAIL", r.get("why") or r.get("error", "")))
    sys.stdout.flush()

    neg = []
    if not args.skip_negative:
        print("")
        print("--- [D] 负例 ---")
        for tag, storage, cpu in [
            ("exceed-limit", "999Gi", "2000m"),
            ("bad-step", "103Gi", "2000m"),
            ("bad-unit", "50G", "2000m"),
            ("no-cpu", "20Gi", None),
        ]:
            n = run_negative(ags, tag, storage, cpu)
            neg.append(n)
            print("  %-14s %-9s [%s] %s" % (
                tag, n["result"], "PASS" if n["pass"] else "FAIL", n["detail"][:120]))
            sys.stdout.flush()

    checked = [r for r in results if "pass" in r]
    passed = sum(1 for r in checked if r["pass"])
    neg_pass = sum(1 for n in neg if n["pass"])
    print("")
    print("=" * 66)
    print("结论汇总")
    print("=" * 66)
    print("%-18s%8s%9s%9s  %s" % ("场景", "声明", "回显", "实测", "结果"))
    print("-" * 66)
    for r in results:
        decl = r.get("instance_storage") or r.get("tool_storage") or "-"
        echo = r.get("instance_echo") or "-"
        act = (str(r["total_gib"]) + "Gi") if r.get("total_gib") else "-"
        mark = "PASS" if r.get("pass") else ("FAIL" if "pass" in r else "ERR")
        print("%-18s%8s%9s%9s  %s" % (r["case"], decl, echo, act, mark))
    print("=" * 66)
    print("正向用例: %d/%d 通过" % (passed, len(checked)))
    if neg:
        print("负例: %d/%d 按预期被拒" % (neg_pass, len(neg)))

    out = {"params": vars(args), "results": results, "negative": neg,
           "summary": {"positive_pass": passed, "positive_total": len(checked),
                       "negative_pass": neg_pass, "negative_total": len(neg)}}
    path = Path("reports/artifacts/tc10-system-disk.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print("")
    print("明细已写入 %s" % path)
    return 0 if passed == len(checked) and neg_pass == len(neg) else 1


if __name__ == "__main__":
    sys.exit(main())
