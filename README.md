# English Coach Agent

一个**理解式**英语学习 Agent（面向中文母语者）：不死记硬背，而是在语境中理解。
三大功能汇成一条数据闭环 —— 生词收集、话题练习（练习模式即时纠错 / 考试模式延迟纠错 + 雅思托福打分）、理解式背单词（FSRS 调度）。

> 设计是源头。所有实现以 `docs/` 为准；改行为先改文档（见 `docs/00-overview.md`）。
> 文档导航见 `docs/00-overview.md`，构建顺序见 `docs/07-implementation-order.md`。

## 当前进度

**MVP 全层（L0–L5）已就绪。** 核心闭环 + 语音 + 日常习惯层（「今日学习」首页、数据导入导出、配置向导、一键启动）均已实现。
进度细节见 `docs/06-roadmap.md`。

| 层 | 内容 |
|---|---|
| L0 | 脚手架：适配器接口 + 配置加载 + DB schema + 前后端空壳 |
| L1 | LocalAdapter(SQLite) 四 Repo + LLM 适配器（OpenAI 兼容 / Claude） |
| L2 | spaCy 切词/lemma/词频过滤 + FSRS 调度器 |
| L3 | 核心闭环：水平基线 → F1 生词收集 → F3a 背词 → F2c 打分 → ErrorAnalysis 错题本 |
| L4 | 语音：STT/TTS 适配器 + F2d 语音对话 + F2a/2b 引导 + F3b 语境造句背 |
| L5 | 日常闭环：今日学习首页 · 导入/导出(JSON + Anki CSV) · 配置向导 · docker-compose 一键启动 |

## 仓库结构

```
backend/     FastAPI 后端（Python 3.11，conda 环境 english-coach）
  app/
    models/      领域实体（VocabEntry / ErrorEntry / PracticeSession / Settings）
    adapters/    适配器（LLM / 存储 Repo / STT / TTS / 发音评估）—— 接口 + 实现
    agents/      五个 Agent（Tokenizer / Tutor / Examiner / MemoryWord / ErrorAnalysis）+ Leveling
    nlp/         spaCy 切词/lemma/词频过滤
    scheduling/  FSRS 间隔重复调度
    api/         HTTP/WS 路由（baseline/vocab/review/practice/voice/today/data/settings）
    db/          schema.sql（四表 DDL）
    config.py    进程级配置（.env → AppConfig）；密钥只在这，绝不入库
    container.py 依赖注入容器（接口可 mock 注入）
    main.py      FastAPI 入口（/api/health, /api/meta, 路由挂载）
  tests/       L0–L5 验证测试（TestClient + mock 容器 + 内存 SQLite，全程离线）
  Dockerfile
frontend/    React + TS + Tailwind（Vite）
  src/panels/  Today / Vocab / Practice / Review / Settings 面板
  Dockerfile, nginx.conf
docs/        设计与决策（源头）
docker-compose.yml
```

## 一键启动（Docker，推荐给开源用户）

```bash
cp backend/.env.example backend/.env      # ⚠️ 必填：至少一个 LLM provider 的连接信息
docker compose up --build                 # 起后端 + 前端
# → 前端 http://localhost:5173 （/api、/ws 经前端 nginx 反代到后端）
```

> **必须先配模型**：`backend/.env` 里不配任何 LLM provider 也能起服务，但所有 AI 功能（打分、背词判断、对话、水平基线）都会返回 409 提示去配模型。最省事是配一个 OpenAI 兼容 provider（DeepSeek/Qwen/Kimi/本地 Ollama 等），见 `backend/.env.example` 的示例。
>
> **默认只绑本机**：前端端口默认绑 `127.0.0.1:5173`（本应用无账号鉴权，却暴露导入导出与会花 key 的端点）。确需局域网/远程访问，启动时设 `FRONTEND_BIND=0.0.0.0` 并自行加鉴权。

想用**纯本地模型**（无需云端 key）：

```bash
docker compose --profile ollama up --build
# 在 backend/.env 里把某 provider 指向 http://ollama:11434/v1（kind=openai_compat，api_key 留空）
# 进容器拉个模型：docker compose exec ollama ollama pull qwen2.5
```

数据（生词/错题/会话）持久化在命名卷 `backend-data`，重建容器不丢。

## 本地开发起步

### 后端

环境用 miniforge/conda（项目固定环境名 `english-coach`，Python 3.11）：

```bash
conda create -n english-coach python=3.11   # 首次
cd backend
conda run -n english-coach python -m pip install -e ".[dev]"
conda run -n english-coach python -m spacy download en_core_web_sm   # F1 切词/水平基线用
cp .env.example .env                          # 按需填写 provider 连接信息
conda run -n english-coach uvicorn app.main:app --reload
# → http://127.0.0.1:8000/api/health
```

可选：纯本地语音（faster-whisper / piper），默认走 OpenAI 兼容协议无需装本组：

```bash
conda run -n english-coach python -m pip install -e ".[voice]"
```

测试 / 质量检查（全程离线，无需真实模型）：

```bash
cd backend
conda run -n english-coach python -m pytest -q
conda run -n english-coach ruff check .
conda run -n english-coach mypy app
```

### 前端

```bash
cd frontend
npm install
npm run dev      # → http://localhost:5173（/api、/ws 代理到后端 8000）
```

## 首次使用：配置向导

新用户在前端「设置」页走完配置向导（首页顶部会有提示横幅督促）：

1. **配模型**：在 `backend/.env` 按 `ENGLISH_COACH_LLM_PROVIDERS__<名字>__...` 填入 provider 连接信息（base_url/api_key/kind），重启后端。密钥只在 `.env`，绝不入库（ADR-006）。
2. **按任务分配模型**：「设置」里给评分/引导/对话/切词各选一个 provider + 模型名，可点「测连通」验证。provider 或 model 任一留空 = 该任务回落到后端默认模型（仅当 `.env` 配了 Claude provider 时才有默认；只配 OpenAI 兼容 provider 时**必须**在此显式分配，否则任务 409）。
3. **测水平基线**：写一小段英文，AI 估算你的 CEFR 等级（标注「AI 估算」，可重测）。基线影响生词过滤与打分（07 红线）。

配好后回「今日」首页，它会把待复习生词、待巩固错题、推荐话题串成今天的学习清单。

## 数据导入 / 导出（「设置」页）

- **JSON 全量备份**：导出含全字段（生词/错题/会话/配置）的备份，可原样**导回本应用**（换机器/迁移用）。导入支持「合并」（默认：同 id 跳过；同词 lemma 把来源句/理解并入已有条目，不覆盖本地复习进度）或「覆盖」（先清空再导）。
- **Anki CSV**：把生词本导出为 Anki 可导入的 CSV。卡正面=单词，**卡背=来源句 + 你历次说出的理解，不含释义**（ADR-014，忠于「不存释义」的 ADR-004）。Anki「文件→导入」选「字段由逗号分隔、允许字段内换行」即可。

## 关键设计不变量（不经新 ADR 不得违反）

- **生词不存释义**，只存 `word + lemma + context_sentences[]`（ADR-004）。
- **考试模式零脚手架**，但允许提前交卷（ADR-005）。
- **无账号，单用户本地优先**，schema 预留 `user_id`（ADR-007）。
- **一切外部依赖皆适配器**（ADR-002）；密钥只来自 `.env`，绝不入库。
- **Anki 卡背放来源句+理解，不放释义；CSV 先行**（ADR-014）。
