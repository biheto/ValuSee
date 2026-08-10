FROM node:22-alpine AS web-builder
WORKDIR /build/web
COPY web/package*.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM python:3.13-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-chi-sim curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 valuesee
COPY pyproject.toml README.md LICENSE ./
COPY app ./app
COPY extension ./extension
COPY --from=web-builder /build/web/dist ./web/dist
RUN pip install --no-cache-dir ".[ocr,llm]" \
    && mkdir -p /app/data/uploads \
    && chown -R valuesee:valuesee /app
USER valuesee
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 CMD curl -fsS http://127.0.0.1:8000/health || exit 1
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
