"""资源清理注册表：确保测试结束后回收创建的实例与工具，避免产生僵尸资源。"""
from __future__ import annotations

import atexit
from typing import Callable


class CleanupRegistry:
    def __init__(self, *, keep: bool = False):
        self._entries: list[tuple[str, Callable[[], None]]] = []
        self.keep = keep
        self._done = False
        atexit.register(self.run_all)

    def register(self, label: str, fn: Callable[[], None]) -> None:
        self._entries.append((label, fn))

    def instance(self, ags, instance_id: str) -> None:
        self.register(f"instance {instance_id}", lambda: ags.stop_instance(instance_id))

    def sandbox(self, sandbox) -> None:
        def _kill():
            from .e2b_api import E2B

            E2B.kill(sandbox)

        self.register(f"sandbox {getattr(sandbox, 'sandbox_id', '?')}", _kill)

    def tool(self, ags, tool_id: str) -> None:
        self.register(f"tool {tool_id}", lambda: ags.delete_tool(tool_id))

    def deployment(self, ags, deployment_id: str) -> None:
        self.register(f"deployment {deployment_id}", lambda: ags.delete_deployment(deployment_id))

    def forget(self, label_substring: str) -> None:
        """移除匹配的资源，避免重复清理。注意：仅移除条目，不执行清理动作。"""
        self._entries = [
            (label, fn) for label, fn in self._entries if label_substring not in label
        ]

    def run_all(self) -> None:
        if self._done:
            return
        self._done = True
        if self.keep:
            print("\n[cleanup] AGS_KEEP_RESOURCES=1，跳过资源回收")
            return
        for label, fn in reversed(self._entries):
            try:
                fn()
                print(f"[cleanup] 已回收 {label}")
            except Exception as exc:  # noqa: BLE001 - 清理失败不应抛异常
                print(f"[cleanup] 回收 {label} 失败: {exc}")
        self._entries.clear()
