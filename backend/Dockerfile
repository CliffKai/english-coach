# 后端镜像（FastAPI）。语音纯本地适配器（[voice]：faster-whisper/piper）默认不装——
# 重依赖、且 ADR-012 默认走 OpenAI 兼容协议（只需主依赖的 openai SDK）。需要纯离线语音的
# 用户自行在镜像里加装 .[voice] 并下载模型。
FROM python:3.11-slim

WORKDIR /app

# 先装依赖（利用层缓存）：仅拷 pyproject，装运行期依赖。
COPY pyproject.toml ./
# editable 安装需要包目录存在；先建占位再正式拷贝源码。
RUN pip install --no-cache-dir --upgrade pip
COPY app ./app
RUN pip install --no-cache-dir .

# spaCy 英文小模型不在 PyPI 依赖里，单独下载（F1 切词/水平基线都要用）。
RUN python -m spacy download en_core_web_sm

# SQLite 数据目录（compose 挂卷持久化）。
RUN mkdir -p /app/data

EXPOSE 8000

# 0.0.0.0 监听以便容器外/前端容器访问。生产不开 --reload。
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
