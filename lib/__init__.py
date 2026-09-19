"""AGS 测试公共库。

提供：
- 统一的环境变量与配置加载
- 腾讯云 Cloud API 客户端（含 call_json 透传）
- E2B 数据面客户端
- 测试结果记录与断言辅助
- 资源清理

敏感信息全部从环境变量或 .env 读取，不落盘到代码。
"""
from .config import CFG
from .ags_api import AgsApi
from .e2b_api import E2B, ensure_domain
from .recorder import Case, Recorder
from .cleanup import CleanupRegistry

__all__ = ["CFG", "AgsApi", "E2B", "ensure_domain", "Case", "Recorder", "CleanupRegistry"]
