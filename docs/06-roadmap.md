# 路线图与进度

## 状态图例
- [ ] 待办  /  [~] 进行中  /  [x] 完成

## 阶段 0：设计（已完成）
- [x] 需求确认（三大功能）
- [x] 形态决策（Web + 语音）
- [x] 架构设计（分层、5 Agent、适配器）
- [x] 数据模型（VocabEntry / ErrorEntry / PracticeSession）
- [x] 关键决策记录（ADR 001–009）
- [x] 实现计划（依赖顺序）—— 见 `07-implementation-order.md`

## 阶段 1：MVP（待 plan 后细化）

MVP 目标 = 跑通**核心学习闭环** + **能被开源用户真正跑起来并形成日常习惯**。
后端 = Python(FastAPI)，含语音，单用户无账号（详见 ADR-007/008/009）。

### 1a. 能跑起来（开源落地基线）
- [x] 项目脚手架（前端 React/TS + 后端 FastAPI + 适配器接口骨架）—— L0 已提交
- [~] `.env.example` + README + docker-compose 一键启动（含可选 Ollama）—— `.env.example` 已落地；docker-compose/README 收尾在 L5
- [ ] 首次配置向导：选存储 → 配模型 provider/key → 测连通性 → 水平基线测试 —— 向导 UI 在 L5（见 07）
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
- [ ] 语音：STT（faster-whisper）+ TTS 适配器接入
- [ ] 功能2d：对话打分（依赖语音）
- [ ] 功能2a/2b：引导模式（即时纠错）
- [ ] 功能3b：语境造句背

### 1d. 习惯养成
- [ ] 「今日学习」聚合首页：待复习生词 + 待巩固错题 + 推荐话题
- [ ] 数据导入/导出：JSON 备份 + 生词本导出 Anki（CSV/.apkg）

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
