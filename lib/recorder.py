"""测试结果记录器：记录每一步的输入、实际输出、判定，并生成 markdown 文档。"""
from __future__ import annotations

import json
import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
ARTIFACTS = ROOT / "reports" / "artifacts"

PASS = "PASS"
FAIL = "FAIL"
BLOCKED = "BLOCKED"
SKIP = "SKIP"


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _fmt(value: Any) -> str:
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False, indent=2)
    except (TypeError, ValueError):
        return repr(value)


@dataclass
class Step:
    name: str
    status: str
    detail: str = ""
    evidence: Any = None
    duration: float = 0.0
    ts: str = field(default_factory=_now)

    @property
    def icon(self) -> str:
        return {"PASS": "✅", "FAIL": "❌", "BLOCKED": "⛔", "SKIP": "⏭️"}.get(self.status, "❔")


class Case:
    """单个测试用例：记录步骤、断言、证据与附件。"""

    def __init__(self, case_id: str, title: str, recorder: "Recorder", *, purpose: str = "",
                 prereq: str = "", network: str = ""):
        self.case_id = case_id
        self.title = title
        self.recorder = recorder
        self.purpose = purpose
        self.prereq = prereq
        self.network = network
        self.steps: list[Step] = []
        self.attachments: list[tuple[str, str]] = []  # (说明, 文件路径)
        self.notes: list[str] = []
        self.started = time.time()
        self.context: dict[str, Any] = {}

    # ------------------------------------------------------------ 记录

    def step(self, name: str, status: str, detail: str = "", evidence: Any = None,
             duration: float = 0.0) -> Step:
        s = Step(name=name, status=status, detail=detail, evidence=evidence, duration=duration)
        self.steps.append(s)
        print(f"  {s.icon} [{self.case_id}] {name}"
              + (f" — {detail}" if detail else ""))
        return s

    def ok(self, name: str, detail: str = "", **kw) -> Step:
        return self.step(name, PASS, detail, **kw)

    def fail(self, name: str, detail: str = "", **kw) -> Step:
        return self.step(name, FAIL, detail, **kw)

    def blocked(self, name: str, detail: str = "", **kw) -> Step:
        return self.step(name, BLOCKED, detail, **kw)

    def skip(self, name: str, detail: str = "", **kw) -> Step:
        return self.step(name, SKIP, detail, **kw)

    def check(self, name: str, condition: bool, detail_pass: str = "", detail_fail: str = "",
              evidence: Any = None) -> bool:
        """断言辅助：condition 为真记 PASS，否则记 FAIL。"""
        if condition:
            self.ok(name, detail_pass, evidence=evidence)
        else:
            self.fail(name, detail_fail or "断言失败", evidence=evidence)
        return bool(condition)

    def note(self, text: str) -> None:
        self.notes.append(text)
        print(f"  ℹ️  [{self.case_id}] {text}")

    def attach(self, label: str, content: str, suffix: str = ".txt") -> Path:
        ARTIFACTS.mkdir(parents=True, exist_ok=True)
        path = ARTIFACTS / f"{self.case_id}-{label}{suffix}"
        path.write_text(content, encoding="utf-8")
        self.attachments.append((label, str(path)))
        return path

    def attach_json(self, label: str, obj: Any) -> Path:
        return self.attach(label, _fmt(obj), ".json")

    # ------------------------------------------------------------ 运行

    def run(self, fn, *args, **kwargs) -> Any:
        """包裹执行体，异常自动记为 FAIL 而不中断整体测试。"""
        try:
            result = fn(*args, **kwargs)
            self.context["result"] = result
            return result
        except Exception as exc:  # noqa: BLE001 - 单用例失败不应中断整体
            self.fail("执行体异常", f"{type(exc).__name__}: {exc}",
                      evidence=traceback.format_exc())
            return None

    # ------------------------------------------------------------ 汇总

    @property
    def status(self) -> str:
        if any(s.status == FAIL for s in self.steps):
            return FAIL
        if any(s.status == BLOCKED for s in self.steps):
            return BLOCKED
        if self.steps and all(s.status == SKIP for s in self.steps):
            return SKIP
        return PASS

    @property
    def duration(self) -> float:
        return time.time() - self.started

    def to_markdown(self) -> str:
        lines: list[str] = []
        lines.append(f"# {self.case_id} {self.title}\n")
        lines.append(f"| 项 | 值 |")
        lines.append(f"|---|---|")
        lines.append(f"| 结论 | **{self.status}** |")
        lines.append(f"| 执行时间 | {datetime.fromtimestamp(self.started).strftime('%Y-%m-%d %H:%M:%S')} |")
        lines.append(f"| 耗时 | {self.duration:.1f}s |")
        if self.network:
            lines.append(f"| 网络模式 | {self.network} |")
        lines.append("")
        if self.purpose:
            lines.append(f"## 测试目的\n\n{self.purpose}\n")
        if self.prereq:
            lines.append(f"## 前置条件\n\n{self.prereq}\n")

        lines.append("## 测试步骤与结果\n")
        lines.append("| # | 步骤 | 结论 | 耗时 | 说明 |")
        lines.append("|---|------|------|------|------|")
        for idx, s in enumerate(self.steps, 1):
            detail = s.detail.replace("\n", " ").replace("|", "\\|")
            lines.append(f"| {idx} | {s.name} | {s.icon} {s.status} | {s.duration:.1f}s | {detail} |")
        lines.append("")

        for idx, s in enumerate(self.steps, 1):
            if s.evidence is None:
                continue
            lines.append(f"### 证据 {idx}: {s.name}\n")
            lines.append("```")
            lines.append(_fmt(s.evidence)[:6000])
            lines.append("```\n")

        if self.notes:
            lines.append("## 备注\n")
            for n in self.notes:
                lines.append(f"- {n}")
            lines.append("")

        if self.attachments:
            lines.append("## 附件\n")
            for label, path in self.attachments:
                lines.append(f"- `{path}` — {label}")
            lines.append("")

        return "\n".join(lines)


class Recorder:
    """收集全部用例并输出汇总文档。"""

    def __init__(self, suite_name: str):
        self.suite_name = suite_name
        self.cases: list[Case] = []
        self.started = time.time()

    def case(self, case_id: str, title: str, **kw) -> Case:
        c = Case(case_id, title, self, **kw)
        self.cases.append(c)
        print(f"\n▶ {case_id} {title}")
        return c

    def write(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.to_markdown(), encoding="utf-8")
        print(f"\n📄 报告已写入: {path}")
        return path

    def write_case_docs(self, out_dir: Path) -> list[Path]:
        out_dir.mkdir(parents=True, exist_ok=True)
        written = []
        for c in self.cases:
            safe = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in c.title)
            p = out_dir / f"{c.case_id}-{safe}.md"
            p.write_text(c.to_markdown(), encoding="utf-8")
            written.append(p)
        return written

    def to_markdown(self) -> str:
        lines = [f"# 测试报告：{self.suite_name}\n"]
        lines.append(f"生成时间：{_now()}　总耗时：{time.time() - self.started:.1f}s\n")
        counts: dict[str, int] = {}
        for c in self.cases:
            counts[c.status] = counts.get(c.status, 0) + 1
        lines.append("## 汇总\n")
        lines.append("| 结论 | 数量 |")
        lines.append("|---|---|")
        for k in (PASS, FAIL, BLOCKED, SKIP):
            if counts.get(k):
                lines.append(f"| {k} | {counts[k]} |")
        lines.append("")
        lines.append("| 用例 | 标题 | 结论 | 通过/失败 | 耗时 |")
        lines.append("|---|---|---|---|---|")
        for c in self.cases:
            npass = sum(1 for s in c.steps if s.status == PASS)
            nfail = sum(1 for s in c.steps if s.status == FAIL)
            lines.append(
                f"| {c.case_id} | {c.title} | {c.status} | {npass}/{nfail} | {c.duration:.1f}s |"
            )
        lines.append("")
        for c in self.cases:
            lines.append("---\n")
            lines.append(c.to_markdown())
        return "\n".join(lines)
