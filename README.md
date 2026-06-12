# English Coach Agent

一个**理解式**英语学习 Agent（面向中文母语者）：不死记硬背，而是在语境中理解。
三大功能汇成一条数据闭环 —— 生词收集、话题练习（练习模式即时纠错 / 考试模式延迟纠错 + 雅思托福打分）、理解式背单词（FSRS 调度）。

> 设计是源头。所有实现以 `docs/` 为准；改行为先改文档（见 `docs/00-overview.md`）。
> 文档导航见 `docs/00-overview.md`，构建顺序见 `docs/07-implementation-order.md`。

## 当前进度

**L0 脚手架已就绪**（适配器接口 + 配置加载 + DB schema + 前后端脚手架）。
按 `docs/07` 的依赖拓扑，下一步是 **L1**（LocalAdapter(SQLite) + LLM 适配器）。

## 仓库结构

```
backend/     FastAPI 后端（Python 3.11，conda 环境 english-coach）
  app/
    models/      领域实体（VocabEntry / ErrorEntry / PracticeSession / Settings）
    adapters/    适配器接口（LLM / 存储 Repo / STT / TTS / 发音评估）—— 仅接口，无实现
    db/          schema.sql（四表 DDL）
    config.py    进程级配置（.env → AppConfig）
    container.py 依赖注入容器（接口可 mock 注入）
    main.py      FastAPI 入口（/api/health, /api/meta）
  tests/       L0 验证测试
frontend/    React + TS + Tailwind（Vite）
docs/        设计与决策（源头）
```

## 本地起步

### 后端

环境用 miniforge/conda（项目固定环境名 `english-coach`，Python 3.11）：

```bash
conda create -n english-coach python=3.11   # 首次
cd backend
conda run -n english-coach python -m pip install -e ".[dev]"
cp .env.example .env                          # 按需填写
conda run -n english-coach uvicorn app.main:app --reload
# → http://127.0.0.1:8000/api/health
```

测试：

```bash
cd backend && conda run -n english-coach python -m pytest -q
```

### 前端

```bash
cd frontend
npm install
npm run dev      # → http://localhost:5173（/api 代理到后端 8000）
```

## 关键设计不变量（不经新 ADR 不得违反）

- **生词不存释义**，只存 `word + lemma + context_sentences[]`（ADR-004）。
- **考试模式零脚手架**，但允许提前交卷（ADR-005）。
- **无账号，单用户本地优先**，schema 预留 `user_id`（ADR-007）。
- **一切外部依赖皆适配器**（ADR-002）。
