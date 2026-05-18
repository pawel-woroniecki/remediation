FROM python:3.11-slim
ARG BUILD_SHA=dev
LABEL org.opencontainers.image.revision=$BUILD_SHA

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py reports.yaml ./
COPY static/ static/

RUN groupadd --gid 1001 appuser \
    && useradd --uid 1001 --gid 1001 --no-create-home appuser
USER appuser

ENV PORT=8080
EXPOSE 8080

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
