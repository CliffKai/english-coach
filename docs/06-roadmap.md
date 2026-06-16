# 路线图与进度

## 状态图例
- [ ] 待办  /  [~] 进行中  /  [x] 完成

## 阶段 0：设计（已完成）
- [x] 需求确认（三大功能）
- [x] 形态决策（Web + 语音）
- [x] 架构设计（分层、5 Agent、适配器）
- [x] 数据模型（VocabEntry / ErrorEntry / PracticeSession）
- [x] 关键决策记录（ADR 001–014，随实现推进追加 010–014）
- [x] 实现计划（依赖顺序）—— 见 `07-implementation-order.md`

## 阶段 1：MVP（已完成，L0–L5 全层落地）

MVP 目标 = 跑通**核心学习闭环** + **能被开源用户真正跑起来并形成日常习惯**。
后端 = Python(FastAPI)，含语音，单用户无账号（详见 ADR-007/008/009）。

### 1a. 能跑起来（开源落地基线）
- [x] 项目脚手架（前端 React/TS + 后端 FastAPI + 适配器接口骨架）—— L0 已提交
- [x] `.env.example` + README + docker-compose 一键启动（含可选 Ollama）—— L5 收尾：根目录 docker-compose（含 ollama profile）+ 前后端 Dockerfile + nginx 反代；README 重写启动/测试/向导/导入导出
- [x] 首次配置向导：选存储 → 配模型 provider/key → 测连通性 → 水平基线测试 —— L5，前端「设置」页向导 UI（模型分配→测连通→基线）+ 后端 `/api/settings`、`/api/providers`、`/api/settings/test-llm`；`/api/meta` 暴露 `needs_wizard`
- [x] 存储层：LocalAdapter（SQLite）先行 —— L1，四个 Repo 已实现并测试
- [x] LLMProvider：OpenAICompatAdapter + ClaudeAdapter —— L1，含 None 发音适配器（ADR-003）

### 1b. 核心闭环
- [x] 功能1：切词 + 逐词问询 + 生词入库（含来源句）—— L2 切词/lemma/词频过滤；L3 TokenizerAgent 编排 + `/api/vocab/{extract,collect,due}`，按 lemma 查重合并（ADR-004/010）
- [x] 功能3a：理解式背单词（基于生词本）—— L3 MemoryWordAgent，来源句复述判断 → FSRS 评级（ADR-011），`/api/review/{next,submit}`
- [x] FSRS 调度器接入 —— L2，按词调度（ADR-010），含评级推进/到期/留存率
- [x] 功能2c：自由写作 + 延迟纠错 + 雅思/托福打分 —— L3 ExaminerAgent（scoring 档，考试模式零脚手架/允许提前交卷 ADR-005，固定 rubric + 多维度打分，综合分 Python 确定性聚合不交 LLM），`/api/practice/score`
- [x] ErrorAnalysisAgent + 错题本 —— L3，紧跟 Examiner 消费隐藏 buffer（07 红线）：确定性转 ErrorEntry 回填错题本 + reasoning 档模式识别复盘，`/api/errors`
- [x] 水平基线分级（首次使用）—— L3 LevelingAgent（scoring 档，固定 rubric + 估算标注），`/api/baseline/{prompt,assess}` 写 `Settings.level_baseline`；并入配置向导 UI 在 L5

### 1c. 语音（已确定纳入 MVP）
- [x] 语音：STT + TTS 适配器接入 —— L4，OpenAI 兼容协议默认 + 本地可选（faster-whisper/piper，懒加载）（ADR-012）；发音/流利度默认空缺并标注，配 API 才有真分（ADR-013）
- [x] 功能2d：对话打分（依赖语音）—— L4，WebSocket 语音对话（STT→ExaminerAgent 自然回话→TTS），提交走 settle_exam 结算链
- [x] 功能2a/2b：引导模式（即时纠错）—— L4，TutorAgent `/api/practice/tutor`（即时纠错+脚手架）
- [x] 功能3b：语境造句背 —— L4，MemoryWordAgent 造短文+翻译检验 `/api/review/passage{,/check}`

### 1d. 习惯养成（L5）
- [x] 「今日学习」聚合首页：待复习生词 + 待巩固错题 + 推荐话题 —— L5，后端 `/api/today`（只读确定性聚合，话题推荐：弱项错题优先/否则内置池轮换）+ 前端 dashboard 首页（默认页）
- [x] 数据导入/导出：JSON 全量备份/迁移 + 生词本导出 Anki（CSV 先行，.apkg 阶段2，见 ADR-014）—— L5，`/api/export/json`、`/api/import/json`（合并按 lemma 并入/覆盖）、`/api/export/anki`（卡背=来源句+理解，不存释义）

## 阶段 2：增强（MVP 后）
- [ ] CloudAdapter（Postgres）+ 多设备
- [ ] 发音评估 AzureAdapter
- [ ] 生词反向应用（写作/口语中检测用上新词）
- [ ] 错题"毕业"机制
- [ ] 错误"举一反三"：高频错误类型生成迷你专项练习
- [ ] 话题联动（功能3b 造句贴近功能2 话题）
- [ ] 练习/造句难度自适应（随近期表现动态调整）
- [ ] 生词来源扩展：URL 文章 / PDF / 字幕(.srt) 导入
- [ ] 学习数据可视化：背词曲线、错误类型分布、雅思分趋势
- [ ] 生词/句子 TTS 发音播放
- [ ] 多语言界面 i18n
- [ ] 仪表盘 / 学习进度可视化

## 已确定的关键决策（原开放项）
- ✅ 后端语言：**Python (FastAPI)** —— spaCy/faster-whisper/FSRS 生态在 Python。详见 ADR-008。
- ✅ 语音：**纳入 MVP**。
- ✅ 账号体系：**无账号，单用户本地优先，schema 预留 user_id**。详见 ADR-007。
