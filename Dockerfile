FROM python:3.13-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY upgates_client.py ./
COPY ai_search ./ai_search
ENV PORT=8080 AI_SEARCH_DATA_DIR=/data PYTHONUNBUFFERED=1
VOLUME /data
EXPOSE 8080
CMD ["python3", "-m", "ai_search.server"]
