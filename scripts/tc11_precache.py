#!/usr/bin/env python3
"""TC-11 镜像预热（PreCacheImage）接口测试。

接口：
  - CreatePreCacheImageTask      提交预热任务（幂等）
  - DescribePreCacheImageTask    查询单镜像预热状态
  - DescribePreCacheImageList    列出全部预热记录（NextToken 分页）

实测要点（2026-11-07，ap-beijing）：
  - 三个接口均可用；SDK 模型缺 PreCacheImageId 字段，需直接传参
  - CreatePreCacheImageTask 幂等：重复提交返回同一 PreCacheImageId，CreateTime 不变
  - 预热来源分 AUTO（自动）与 EXPLICIT（显式）
  - 返回字段比 SDK 模型丰富：IdleTTL / CachedImageSizeBytes / SourceType / Scopes 等

用法：
    python3 scripts/tc11_precache.py              # 全量测试
    python3 scripts/tc11_precache.py --list       # 只看列表
    python3 scripts/tc11_precache.py --verify IMG # 校验指定镜像
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib import CFG, AgsApi  # noqa: E402


def call(ags, name, payload):
    t0 = time.time()
    try:
        r = ags.call(name, payload)
        r.pop("RequestId", None)
        return {"ok": True, "ms": round((time.time() - t0) * 1000), "data": r}
    except Exception as exc:  # noqa: BLE001
        s = str(exc)
        code = s.split("]")[0].strip("[") if s.startswith("[") else type(exc).__name__
        return {"ok": False, "ms": round((time.time() - t0) * 1000), "code": code, "msg": s[:300]}


def list_all(ags, limit_pages=20):
    recs, tok, pages = [], None, 0
    while pages < limit_pages:
        p = {} if not tok else {"NextToken": tok}
        r = ags.call("DescribePreCacheImageList", p)
        recs += r.get("PreCacheImageList") or []
        tok = r.get("NextToken")
        pages += 1
        if not tok:
            break
    return recs


def print_list(recs):
    print("%-20s %-9s %-9s %8s  %s" % ("PreCacheImageId", "Status", "Source", "GiB", "Image"))
    print("-" * 108)
    for x in recs:
        size = (x.get("CachedImageSizeBytes") or 0) / 1024.0 ** 3
        print("%-20s %-9s %-9s %8.2f  %s" % (
            x.get("PreCacheImageId", ""), x.get("Status", ""),
            x.get("SourceType", "-"), size, (x.get("Image") or "")[:56]))
    from collections import Counter  # noqa: PLC0415
    print()
    print("Status:", dict(Counter(x.get("Status") for x in recs)))
    print("SourceType:", dict(Counter(x.get("SourceType") for x in recs)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true", help="只列出预热记录")
    ap.add_argument("--verify", help="校验指定镜像的预热状态")
    ap.add_argument("--skip-negative", action="store_true")
    args = ap.parse_args()

    ags = AgsApi()
    checks = []

    def add(name, ok, detail=""):
        checks.append({"name": name, "pass": bool(ok), "detail": detail})
        print("  %-40s %s  %s" % (name, "PASS" if ok else "FAIL", detail[:70]))

    print("=== TC-11 镜像预热接口测试 ===")
    print("region=%s" % ags.region)
    print()

    print("[1] DescribePreCacheImageList 分页拉取")
    recs = list_all(ags)
    print_list(recs)
    add("列表接口可用", len(recs) > 0, "%d 条记录" % len(recs))
    add("记录含 PreCacheImageId", all(x.get("PreCacheImageId") for x in recs))
    add("记录含 ImageDigest", all(x.get("ImageDigest") for x in recs))

    if args.list:
        return 0

    print()
    print("[2] DescribePreCacheImageTask 按 Image 查询")
    target = args.verify or CFG.image
    r = call(ags, "DescribePreCacheImageTask",
             {"Image": target, "ImageRegistryType": CFG.image_registry_type})
    if r["ok"]:
        d = r["data"]
        print("  Status=%s SourceType=%s size=%.2fGiB" % (
            d.get("Status"), d.get("SourceType"),
            (d.get("CachedImageSizeBytes") or 0) / 1024.0 ** 3))
        add("按 Image 查询成功", True)
        add("状态为 Success", d.get("Status") == "Success", d.get("Status", ""))
        PID = d.get("PreCacheImageId")
    else:
        add("按 Image 查询成功", False, r.get("msg", ""))
        PID = None

    print()
    print("[3] 按 PreCacheImageId 查询（SDK 模型无此字段）")
    if PID:
        r2 = call(ags, "DescribePreCacheImageTask", {"PreCacheImageId": PID})
        add("按 PreCacheImageId 查询成功", r2["ok"], r2.get("code", ""))

    print()
    print("[4] CreatePreCacheImageTask 幂等性")
    if PID:
        before = r["data"]
        c = call(ags, "CreatePreCacheImageTask",
                 {"Image": target, "ImageRegistryType": CFG.image_registry_type})
        add("重复提交成功", c["ok"])
        if c["ok"]:
            add("返回同一 PreCacheImageId", c["data"].get("PreCacheImageId") == PID,
                c["data"].get("PreCacheImageId", ""))
            add("返回 Scopes 字段", "Scopes" in c["data"], str(c["data"].get("Scopes")))
            after = call(ags, "DescribePreCacheImageTask", {"PreCacheImageId": PID})["data"]
            add("CreateTime 未变化（未触发重跑）",
                after.get("CreateTime") == before.get("CreateTime"),
                after.get("CreateTime", ""))

    if not args.skip_negative:
        print()
        print("[5] 负例")
        n1 = call(ags, "CreatePreCacheImageTask",
                  {"Image": "ccr.ccs.tencentyun.com/nonexistent/repo:v0",
                   "ImageRegistryType": "personal"})
        add("不存在的镜像被拒", not n1["ok"] and n1.get("code") == "ResourceNotFound.Image",
            n1.get("code", ""))

        n2 = call(ags, "CreatePreCacheImageTask", {"Image": target})
        add("缺 ImageRegistryType 被拒", not n2["ok"] and "MissingParameter" in str(n2.get("code")),
            n2.get("code", ""))

        n3 = call(ags, "DescribePreCacheImageTask", {"Image": target})
        add("查询缺 registry type 被拒", not n3["ok"], n3.get("code", ""))

        n4 = call(ags, "DescribePreCacheImageList", {"Limit": 10})
        add("列表不支持的参数被拒", not n4["ok"] and "UnknownParameter" in str(n4.get("code")),
            n4.get("code", ""))

    passed = sum(1 for c in checks if c["pass"])
    print()
    print("=" * 70)
    print("结论：%d/%d 检查点通过" % (passed, len(checks)))
    print("=" * 70)

    out = {"region": ags.region, "records": recs, "checks": checks,
           "summary": {"pass": passed, "total": len(checks)}}
    p = Path("reports/artifacts/tc11-precache.json")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print("明细已写入 %s" % p)
    return 0 if passed == len(checks) else 1


if __name__ == "__main__":
    sys.exit(main())
