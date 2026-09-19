"""腾讯云 AGS 控制面 API 封装。

统一处理：
- 客户端初始化（region / endpoint）
- typed 调用与 call_json 透传
- 异常包装，保留 RequestId
- 轮询等待工具/实例进入目标状态
"""
from __future__ import annotations

import json
import time
from typing import Any

from tencentcloud.ags.v20250920 import ags_client, models
from tencentcloud.common import credential
from tencentcloud.common.exception.tencent_cloud_sdk_exception import TencentCloudSDKException
from tencentcloud.common.profile.client_profile import ClientProfile
from tencentcloud.common.profile.http_profile import HttpProfile

from .config import CFG

ENDPOINT = "ags.tencentcloudapi.com"


class AgsError(RuntimeError):
    """带 RequestId 的 AGS 调用异常。"""

    def __init__(self, code: str, message: str, request_id: str | None = None):
        self.code = code
        self.message = message
        self.request_id = request_id
        super().__init__(f"[{code}] {message} (RequestId: {request_id})")


class AgsApi:
    def __init__(self, region: str | None = None):
        CFG.require_cloud()
        self.region = region or CFG.region
        cred = credential.Credential(CFG.secret_id, CFG.secret_key)
        http = HttpProfile(endpoint=ENDPOINT)
        self._client = ags_client.AgsClient(
            cred, self.region, ClientProfile(httpProfile=http)
        )
        self._models = models

    # ------------------------------------------------------------------ 通用

    def call(self, action: str, payload: dict, *, retries: int = 0, retry_wait: float = 5.0) -> dict:
        """透传调用云 API，返回 Response 字典。call_json 用于 SDK 未发布 typed model 的场景。"""
        last: Exception | None = None
        for attempt in range(retries + 1):
            try:
                resp = self._client.call_json(action, payload)
                return resp.get("Response", resp)
            except TencentCloudSDKException as exc:
                last = AgsError(getattr(exc, "code", "Unknown"), str(exc), getattr(exc, "requestId", None))
                if attempt < retries:
                    time.sleep(retry_wait)
            except Exception as exc:  # noqa: BLE001 - 网络层异常统一包装
                last = exc
                if attempt < retries:
                    time.sleep(retry_wait)
        raise last  # type: ignore[misc]

    # ------------------------------------------------------- 沙箱工具 (Tool)

    def create_tool(self, payload: dict, **kw) -> dict:
        return self.call("CreateSandboxTool", payload, **kw)

    def describe_tools(self, payload: dict | None = None) -> dict:
        return self.call("DescribeSandboxToolList", payload or {"Limit": 100})

    def get_tool(self, tool_id: str) -> dict | None:
        tools = self.describe_tools({"ToolIds": [tool_id]}).get("SandboxToolSet", [])
        return tools[0] if tools else None

    def find_tool_by_name(self, name: str) -> dict | None:
        for tool in self.describe_tools().get("SandboxToolSet", []):
            if tool.get("ToolName") == name:
                return tool
        return None

    def delete_tool(self, tool_id: str) -> dict:
        return self.call("DeleteSandboxTool", {"ToolId": tool_id})

    def wait_tool(self, tool_id: str, *, want: str = "ACTIVE", timeout: float = 600, interval: float = 5.0) -> dict:
        deadline = time.time() + timeout
        last: dict | None = None
        while time.time() < deadline:
            last = self.get_tool(tool_id)
            if last is None:
                raise AgsError("NotFound", f"工具 {tool_id} 查询为空")
            status = last.get("Status")
            if status == want:
                return last
            if status in ("FAILED", "CREATE_FAILED", "DELETED") and want != status:
                raise AgsError(
                    status,
                    f"工具 {tool_id} 进入终态 {status}: {last.get('StatusReason', '')}",
                )
            time.sleep(interval)
        raise AgsError("Timeout", f"等待工具 {tool_id} 变为 {want} 超时，最后状态: {(last or {}).get('Status')}")

    # ----------------------------------------------------- 沙箱实例 (Instance)

    def start_instance(self, payload: dict, **kw) -> dict:
        return self.call("StartSandboxInstance", payload, **kw)

    def start_instance_id(self, payload: dict, **kw) -> str | None:
        """启动实例并直接返回 InstanceId（兼容两种返回结构）。"""
        resp = self.start_instance(payload, **kw)
        return (resp.get("Instance") or {}).get("InstanceId") or resp.get("InstanceId")

    def describe_instances(self, payload: dict | None = None) -> dict:
        return self.call("DescribeSandboxInstanceList", payload or {"Limit": 100})

    def get_instance(self, instance_id: str) -> dict | None:
        resp = self.describe_instances({"InstanceIds": [instance_id]})
        items = resp.get("InstanceSet") or resp.get("SandboxInstanceSet") or []
        return items[0] if items else None

    def stop_instance(self, instance_id: str) -> dict:
        return self.call("StopSandboxInstance", {"InstanceId": instance_id})

    def pause_instance(self, instance_id: str, memory: str | None = None) -> dict:
        payload: dict = {"InstanceId": instance_id}
        if memory:
            payload["Memory"] = memory
        return self.call("PauseSandboxInstance", payload)

    def resume_instance(self, instance_id: str, timeout: str | None = None) -> dict:
        payload: dict = {"InstanceId": instance_id}
        if timeout:
            payload["Timeout"] = timeout
        return self.call("ResumeSandboxInstance", payload)

    def update_instance(self, payload: dict) -> dict:
        return self.call("UpdateSandboxInstance", payload)

    def acquire_token(self, instance_id: str) -> dict:
        return self.call("AcquireSandboxInstanceToken", {"InstanceId": instance_id})

    def wait_instance(self, instance_id: str, *, want: str = "RUNNING", timeout: float = 900, interval: float = 5.0) -> dict:
        deadline = time.time() + timeout
        last: dict | None = None
        while time.time() < deadline:
            last = self.get_instance(instance_id)
            if last is None:
                raise AgsError("NotFound", f"实例 {instance_id} 查询为空")
            status = last.get("Status")
            if status == want:
                return last
            if status in ("FAILED", "STARTING_FAILED", "STOPPED") and want not in (status,):
                raise AgsError(
                    status,
                    f"实例 {instance_id} 进入终态 {status}: {last.get('StopReason', '')}",
                )
            time.sleep(interval)
        raise AgsError("Timeout", f"等待实例 {instance_id} 变为 {want} 超时，最后状态: {(last or {}).get('Status')}")

    def wait_instance_gone(self, instance_id: str, *, timeout: float = 300, interval: float = 3.0) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            inst = self.get_instance(instance_id)
            if inst is None or inst.get("Status") in ("STOPPED", "FAILED"):
                return True
            time.sleep(interval)
        return False

    # ---------------------------------------------------------- API Key

    def create_api_key(self, name: str) -> dict:
        return self.call("CreateAPIKey", {"Name": name})

    def describe_api_keys(self) -> dict:
        return self.call("DescribeAPIKeyList", {"Limit": 100})

    def delete_api_key(self, key_id: str) -> dict:
        return self.call("DeleteAPIKey", {"KeyId": key_id})

    # ------------------------------------------------- 镜像预热 (PreCache)

    def create_precache(self, image: str, registry_type: str = "enterprise") -> dict:
        return self.call("CreatePreCacheImageTask", {"Image": image, "ImageRegistryType": registry_type})

    def describe_precache(self, image: str, registry_type: str = "enterprise") -> dict:
        return self.call(
            "DescribePreCacheImageTask", {"Image": image, "ImageRegistryType": registry_type}
        )

    # --------------------------------------------------- 弹性部署 (Deployment)

    def create_deployment(self, payload: dict) -> dict:
        return self.call("CreateDeployment", payload)

    def describe_deployment(self, deployment_id: str) -> dict:
        return self.call("DescribeDeployment", {"DeploymentId": deployment_id})

    def describe_deployments(self, payload: dict | None = None) -> dict:
        return self.call("DescribeDeploymentList", payload or {"Limit": 100})

    def modify_deployment(self, payload: dict) -> dict:
        return self.call("ModifyDeployment", payload)

    def delete_deployment(self, deployment_id: str) -> dict:
        return self.call("DeleteDeployment", {"DeploymentId": deployment_id})

    def acquire_deployment_token(self, deployment_id: str) -> dict:
        return self.call("AcquireDeploymentToken", {"DeploymentId": deployment_id})


def dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2)
