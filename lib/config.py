"""配置加载：环境变量优先，其次 /root/ags/.env。"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    """极简 .env 加载器，不覆盖已存在的环境变量。"""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("'\"")
        if key and key not in os.environ:
            os.environ[key] = value


_load_dotenv(ROOT / ".env")


def env(key: str, default: str | None = None, *, required: bool = False) -> str | None:
    value = os.environ.get(key, default)
    if required and not value:
        raise RuntimeError(f"缺少必需的环境变量: {key}")
    return value


@dataclass(frozen=True)
class Config:
    # --- 腾讯云控制面 ---
    secret_id: str | None = field(default_factory=lambda: env("TENCENTCLOUD_SECRET_ID"))
    secret_key: str | None = field(default_factory=lambda: env("TENCENTCLOUD_SECRET_KEY"))
    region: str = field(default_factory=lambda: env("TENCENTCLOUD_REGION", "ap-beijing") or "ap-beijing")

    # --- E2B 数据面 ---
    e2b_api_key: str | None = field(default_factory=lambda: env("E2B_API_KEY"))
    e2b_domain: str = field(
        default_factory=lambda: env("E2B_DOMAIN", f"{env('TENCENTCLOUD_REGION', 'ap-beijing')}.tencentags.com")
        or "ap-beijing.tencentags.com"
    )

    # --- 网络 ---
    vpc_id: str = field(default_factory=lambda: env("AGS_VPC_ID", "vpc-ovochv3a") or "")
    subnet_id: str = field(default_factory=lambda: env("AGS_SUBNET_ID", "subnet-pac3o08j") or "")
    security_group_id: str | None = field(default_factory=lambda: env("AGS_SECURITY_GROUP_ID"))

    # --- TCR 镜像仓库 ---
    tcr_instance: str | None = field(default_factory=lambda: env("TCR_INSTANCE"))
    tcr_username: str | None = field(default_factory=lambda: env("TCR_USERNAME"))
    tcr_password: str | None = field(default_factory=lambda: env("TCR_PASSWORD"))
    tcr_domain: str = field(
        default_factory=lambda: env("TCR_DOMAIN", "euson-tcr.tencentcloudcr.com") or "euson-tcr.tencentcloudcr.com"
    )
    # 被测沙箱镜像（须自带 envd，或通过镜像卷挂载 envd）
    image: str = field(
        default_factory=lambda: env("AGT_IMAGE", "euson-tcr.tencentcloudcr.com/sandbox/sandbox:v1")
        or "euson-tcr.tencentcloudcr.com/sandbox/sandbox:v1"
    )
    image_registry_type: str = field(
        default_factory=lambda: env("AGT_IMAGE_REGISTRY_TYPE", "enterprise") or "enterprise"
    )
    # envd 在镜像内的路径
    envd_path: str = field(default_factory=lambda: env("AGT_ENVD_PATH", "/usr/bin/envd") or "/usr/bin/envd")

    # --- 被测资源（由用户回填）---
    role_arn: str | None = field(default_factory=lambda: env("AGS_ROLE_ARN"))
    bucket_library_id: str | None = field(default_factory=lambda: env("AGENTBUCKET_LIBRARY_ID"))
    bucket_space_id: str | None = field(default_factory=lambda: env("AGENTBUCKET_SPACE_ID"))
    bucket_library_secret: str | None = field(default_factory=lambda: env("AGENTBUCKET_LIBRARY_SECRET"))
    cfs_file_system_id: str | None = field(default_factory=lambda: env("AGENTCFS_FILE_SYSTEM_ID"))
    cfs_path: str = field(default_factory=lambda: env("AGENTCFS_PATH", "/") or "/")

    # --- 测试开关 ---
    run_prefix: str = field(default_factory=lambda: env("AGS_TEST_PREFIX", "agstest") or "agstest")
    keep_resources: bool = field(
        default_factory=lambda: (env("AGS_KEEP_RESOURCES", "0") or "0").lower() in ("1", "true", "yes")
    )

    def vpc_config(self) -> dict:
        cfg: dict = {"SubnetIds": [self.subnet_id]}
        if self.security_group_id:
            cfg["SecurityGroupIds"] = [self.security_group_id]
        return cfg

    def vpc_network(self) -> dict:
        return {"NetworkMode": "VPC", "VpcConfig": self.vpc_config()}

    def public_network(self) -> dict:
        return {"NetworkMode": "PUBLIC"}

    def sandbox_network(self) -> dict:
        return {"NetworkMode": "SANDBOX"}

    def require_cloud(self) -> None:
        missing = [k for k, v in (("TENCENTCLOUD_SECRET_ID", self.secret_id),
                                  ("TENCENTCLOUD_SECRET_KEY", self.secret_key)) if not v]
        if missing:
            raise RuntimeError(f"缺少腾讯云凭据: {', '.join(missing)}")

    def require_e2b(self) -> None:
        if not self.e2b_api_key:
            raise RuntimeError("缺少 E2B_API_KEY")


CFG = Config()
