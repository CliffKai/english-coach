"""English Coach Agent — 后端应用包。

分层（见 docs/02-architecture.md）：
- app.models   领域实体（VocabEntry / ErrorEntry / PracticeSession / Settings）
- app.adapters 适配器接口（一切外部依赖皆接口，ADR-002）
- app.db       存储 schema / DDL
- app.config   配置加载
- app.main     FastAPI 入口
"""

__version__ = "0.0.1"
