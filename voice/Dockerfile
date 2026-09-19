FROM --platform=linux/arm64 python:3.12-slim

ENV PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
RUN pip install --no-cache-dir uv==0.9.5

WORKDIR /app
COPY agent /app/agent
COPY voice /app/voice
WORKDIR /app/voice
RUN uv sync --frozen --no-dev

EXPOSE 8080
CMD ["uv", "run", "--no-sync", "python", "-m", "jhola_voice.server"]
