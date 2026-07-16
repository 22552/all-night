FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000

WORKDIR /app
COPY night.py ./

RUN pip install --no-cache-dir "uvicorn[standard]"

EXPOSE 8000

CMD ["sh", "-c", "uvicorn night:app --host 0.0.0.0 --port ${PORT}"]

