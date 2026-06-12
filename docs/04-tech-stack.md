# 技术选型

## 前端
- **React + TypeScript + Tailwind**
- 录音：`MediaRecorder` API
- 流式对话/语音：WebSocket

## 后端
- **FastAPI（Python）** —— 生态适合 NLP/切词/FSRS；或 Node（若想前后端同语言）
- 切词/词元还原：**spaCy**（lemma 还原比纯 LLM 更稳、更省）
- 间隔重复：**FSRS** 现成库（参考 awesome-fsrs）

## 适配器（核心：一切外部依赖皆可换）

### LLMProvider —— 多模型支持
业务只依赖 `LLMProvider` 接口。

```
LLMProvider 接口
  ├── ClaudeAdapter        (Anthropic API，原生协议，能力最强→评分)
  ├── OpenAIAdapter        (GPT)
  ├── OpenAICompatAdapter  (兼容 OpenAI 协议：通义/DeepSeek/Kimi/智谱/vLLM/Ollama/LM Studio)
  └── LocalAdapter         (本地：Ollama / vLLM / llama.cpp)
```

> **关键洞察**：80% 的模型（含多数自部署方案）兼容 OpenAI `/v1/chat/completions` 协议。
> 做好一个 `OpenAICompatAdapter`，填不同 `base_url` + `api_key` + `model_name` 即可覆盖绝大多数云/自部署模型。Claude 单独原生适配。

**按任务分配模型**（用户可配置）：
```yaml
models:
  scoring:      { provider: claude,   model: opus }     # 评分要最强
  reasoning:    { provider: claude,   model: sonnet }   # 引导/复盘
  tokenize:     { provider: ollama,   model: qwen2.5 }  # 切词，本地省钱
  conversation: { provider: deepseek, model: chat }     # 高频对话
```

### StorageRepository —— 存储可切换
```
WordRepository / ErrorRepository / SessionRepository 接口
  ├── LocalAdapter   (SQLite / 文件)  —— 简单、隐私、单机
  └── CloudAdapter   (Postgres)       —— 多设备、未来多用户
```
用户在设置里切换 `storage_backend`。

### STTProvider —— 语音转文字
```
STTProvider 接口
  ├── WhisperLocalAdapter  (faster-whisper，本地)
  └── WhisperApiAdapter / 其他云端 STT
```

### TTSProvider —— 文字转语音
```
TTSProvider 接口
  ├── LocalAdapter   (本地 TTS)
  └── CloudAdapter   (云端 TTS)
```

### PronunciationProvider —— 发音评估（可选，默认关闭）
```
PronunciationProvider 接口（默认 NoneAdapter）
  ├── NoneAdapter   → 第一版默认。口语打分时发音/流利度维度
  │                   标注"基于文本估算，仅供参考"
  └── AzureAdapter  → 用户填 key 启用，音素级真实评分
```
> **决策**：不自研发音评估（声学难题，投入产出差）。留适配器接口，
> 默认 NoneAdapter，需要精准发音分时接 Azure Pronunciation Assessment / 讯飞 等。详见 ADR-003。

## 模型/服务密钥管理
- 用户在设置中填写各 provider 的 `base_url` / `api_key` / `model_name`。
- 本地部署模型（Ollama 等）无需 key，仅填 `base_url`。
