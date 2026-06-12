# 数据模型

> 数据是本项目的核心闭环。两条数据河流（生词、错误）汇入统一的用户画像。

## 实体关系

```
User
 ├── VocabEntry    生词条目   ← 功能1产出，功能3消费
 ├── ErrorEntry    错题条目   ← 功能2产出
 ├── PracticeSession 练习会话 ← 功能2
 └── Settings      配置
```

## VocabEntry（生词条目）

| 字段 | 说明 |
|---|---|
| `id` | 主键 |
| `user_id` | 所属用户 |
| `word` | 原词 |
| `lemma` | 词元（词形还原后） |
| `context_sentences[]` | **来源句列表**（核心！同词不同义存多条） |
| `status` | new / learning / known |
| `fsrs_state` | FSRS 状态：难度、稳定性、到期日、复习次数 |
| `user_understanding` | 用户复习时说出的理解（历史记录，非标准答案） |
| `source_text_id` | 来源文本引用 |
| `created_at` | 收集时间 |

> **关键决策**：**不存释义**。意思在复习时由用户重新理解出来，来源句即是消歧的钥匙。详见 `05-decisions.md` ADR-004。

## ErrorEntry（错题条目）

| 字段 | 说明 |
|---|---|
| `id` | 主键 |
| `user_id` | 所属用户 |
| `type` | grammar / collocation / spelling / logic / vocabulary / pronunciation |
| `original` | 用户原句（出错的） |
| `correction` | 修正后 |
| `explanation` | 错误解释 |
| `session_id` | 来源练习会话 |
| `topic` | 话题 |
| `severity` | 严重程度 |
| `resolved` | 是否已掌握（连续N次未犯则标记，复盘不再唠叨） |
| `created_at` | 时间 |

## PracticeSession（练习会话）

| 字段 | 说明 |
|---|---|
| `id` | 主键 |
| `user_id` | 所属用户 |
| `mode` | guided_write / guided_speak / free_write / dialogue |
| `topic` | 话题 |
| `transcript` | 全程文本/对话记录 |
| `scores` | 雅思/托福各维度分数（JSON） |
| `error_ids[]` | 本次产生的错误引用 |
| `summary` | 复盘总结 |
| `ended_early` | 是否提前交卷 |
| `created_at` | 时间 |

## Settings（配置）

| 字段 | 说明 |
|---|---|
| `storage_backend` | local / cloud |
| `scoring_standard` | IELTS / TOEFL |
| `target_band` | 目标分数 |
| `native_lang` | 母语（默认中文） |
| `level_baseline` | 水平基线（CEFR / 估算雅思分） |
| `voice_enabled` | 是否启用语音 |
| `model_config` | 各任务的模型分配（见 04-tech-stack） |
| `pronunciation_provider` | none / azure / ...（默认 none） |
