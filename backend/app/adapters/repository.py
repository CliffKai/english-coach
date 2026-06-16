"""存储 Repository 接口（docs/04 StorageRepository）。

业务代码只依赖这些接口；实现 L1 起步用 LocalAdapter(SQLite)，后续 CloudAdapter(Postgres)。
所有方法带 user_id（默认 local-user，ADR-007），为未来多用户 fork 预留。

注：接口用 async 定义，便于 L1 既能套同步 SQLite（线程池）也能套异步 Postgres。
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.models import (
    DEFAULT_USER_ID,
    ErrorEntry,
    PracticeSession,
    Settings,
    VocabEntry,
)


class WordRepository(ABC):
    """生词本存取（功能1产出 / 功能3消费）。"""

    @abstractmethod
    async def add(self, entry: VocabEntry) -> VocabEntry: ...

    @abstractmethod
    async def get(self, entry_id: str, *, user_id: str = DEFAULT_USER_ID) -> VocabEntry | None: ...

    @abstractmethod
    async def get_by_lemma(
        self, lemma: str, *, user_id: str = DEFAULT_USER_ID
    ) -> VocabEntry | None:
        """按词元查重——同词不同义应追加 context_sentences 而非新建（ADR-004）。"""

    @abstractmethod
    async def list(self, *, user_id: str = DEFAULT_USER_ID) -> list[VocabEntry]: ...

    @abstractmethod
    async def list_due(
        self, *, user_id: str = DEFAULT_USER_ID, limit: int | None = None
    ) -> list[VocabEntry]:
        """FSRS 到期复习队列（L2 调度器消费此结果，功能3）。"""

    @abstractmethod
    async def update(self, entry: VocabEntry) -> VocabEntry: ...

    @abstractmethod
    async def delete(self, entry_id: str, *, user_id: str = DEFAULT_USER_ID) -> None: ...


class ErrorRepository(ABC):
    """错题本存取（功能2考试模式产出）。"""

    @abstractmethod
    async def add(self, entry: ErrorEntry) -> ErrorEntry: ...

    @abstractmethod
    async def add_many(self, entries: list[ErrorEntry]) -> list[ErrorEntry]:
        """批量写入——ErrorAnalysis 复盘后一次性回填错题本。"""

    @abstractmethod
    async def get(self, entry_id: str, *, user_id: str = DEFAULT_USER_ID) -> ErrorEntry | None: ...

    @abstractmethod
    async def list(
        self, *, user_id: str = DEFAULT_USER_ID, resolved: bool | None = None
    ) -> list[ErrorEntry]:
        """resolved=None 全部；False 仅待巩固（首页错题区用）。"""

    @abstractmethod
    async def update(self, entry: ErrorEntry) -> ErrorEntry: ...

    @abstractmethod
    async def delete(self, entry_id: str, *, user_id: str = DEFAULT_USER_ID) -> None:
        """删除一条错题（覆盖式导入恢复用，L5）。"""


class SessionRepository(ABC):
    """练习会话存取（功能2）。"""

    @abstractmethod
    async def add(self, session: PracticeSession) -> PracticeSession: ...

    @abstractmethod
    async def get(
        self, session_id: str, *, user_id: str = DEFAULT_USER_ID
    ) -> PracticeSession | None: ...

    @abstractmethod
    async def list(self, *, user_id: str = DEFAULT_USER_ID) -> list[PracticeSession]: ...

    @abstractmethod
    async def update(self, session: PracticeSession) -> PracticeSession: ...

    @abstractmethod
    async def delete(self, session_id: str, *, user_id: str = DEFAULT_USER_ID) -> None:
        """删除一条会话（覆盖式导入恢复用，L5）。"""


class SettingsRepository(ABC):
    """用户配置存取（单行 per user）。配置向导（L5）与各功能读基线都经此。"""

    @abstractmethod
    async def get(self, *, user_id: str = DEFAULT_USER_ID) -> Settings | None: ...

    @abstractmethod
    async def save(self, settings: Settings) -> Settings: ...
