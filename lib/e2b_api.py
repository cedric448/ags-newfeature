"""E2B 数据面封装。

AGS 通过 E2B 兼容协议提供数据面。注意：
- `Sandbox.create(template=...)` 的 template 是 **ToolName**，不是 `sdt-...` 形式的 ToolId。
- 实例级挂载通过 `metadata["x-mounts"]`（JSON 字符串）传入。
- 部分挂载目录（如 CFS / AgentBucket）需要 `user="root"` 才能访问。
"""
from __future__ import annotations

import contextlib
import json
import os
from typing import Any

from .config import CFG


def ensure_domain() -> None:
    """确保 E2B SDK 使用 AGS 的域名和 Key。"""
    CFG.require_e2b()
    os.environ["E2B_DOMAIN"] = CFG.e2b_domain
    os.environ["E2B_API_KEY"] = CFG.e2b_api_key or ""


def _sandbox_cls():
    ensure_domain()
    from e2b_code_interpreter import Sandbox  # noqa: PLC0415 - 延迟导入以先设置环境变量

    return Sandbox


class E2B:
    """E2B 数据面薄封装。"""

    @staticmethod
    def create(
        template: str,
        *,
        timeout: int = 600,
        metadata: dict[str, str] | None = None,
        mounts: list[dict] | None = None,
        **kwargs: Any,
    ):
        """创建沙箱实例。

        template: ToolName
        mounts:   实例级挂载，会被序列化到 metadata["x-mounts"]
        """
        meta = dict(metadata or {})
        if mounts is not None:
            meta["x-mounts"] = json.dumps(mounts)
        return _sandbox_cls().create(template=template, timeout=timeout, metadata=meta, **kwargs)

    @staticmethod
    def connect(sandbox_id: str, **kwargs: Any):
        ensure_domain()
        try:
            from e2b import Sandbox as BaseSandbox  # noqa: PLC0415

            return BaseSandbox.connect(sandbox_id, **kwargs)
        except Exception:  # noqa: BLE001 - 回退到 code-interpreter 客户端
            return _sandbox_cls().connect(sandbox_id, **kwargs)

    @staticmethod
    def kill(sandbox) -> bool:
        if sandbox is None:
            return False
        with contextlib.suppress(Exception):
            sandbox.kill()
            return True
        return False

    @staticmethod
    def run(sandbox, cmd: str, *, user: str = "root", timeout: int = 120) -> tuple[int, str, str]:
        """执行 shell 命令，返回 (exit_code, stdout, stderr)。"""
        res = sandbox.commands.run(cmd, user=user, timeout=timeout)
        return (
            getattr(res, "exit_code", -1),
            getattr(res, "stdout", "") or "",
            getattr(res, "stderr", "") or "",
        )


def mounts(name: str, mount_path: str | None = None, sub_path: str | None = None,
           read_only: bool | None = None) -> list[dict]:
    """构造 x-mounts 载荷，省略未指定的字段。"""
    item: dict[str, Any] = {"name": name}
    if mount_path is not None:
        item["mountPath"] = mount_path
    if sub_path is not None:
        item["subPath"] = sub_path
    if read_only is not None:
        item["readOnly"] = read_only
    return [item]
