FROM python:3.13-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY upgates_client.py ./
COPY ai_search ./ai_search
# MALLOC_ARENA_MAX: the threaded HTTP server otherwise lets glibc keep one memory arena per
# thread, which grows the process far beyond what Python actually uses.
ENV PORT=8080 AI_SEARCH_DATA_DIR=/data PYTHONUNBUFFERED=1 MALLOC_ARENA_MAX=2
VOLUME /data
EXPOSE 8080
CMD ["python3", "-m", "ai_search.server"]
