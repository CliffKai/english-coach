"""HTTP 路由层（L3 起）。

按功能拆 router：baseline（水平基线）/ vocab（F1 生词）/ review（F3a 背词）。
路由只做「取依赖 → 调 Agent → 形塑响应」，业务逻辑在 Agent 层。依赖经 app.api.deps
从容器（DI）取，便于测试整体替换。
"""

from app.api.baseline import router as baseline_router
from app.api.review import router as review_router
from app.api.vocab import router as vocab_router

__all__ = ["baseline_router", "vocab_router", "review_router"]
