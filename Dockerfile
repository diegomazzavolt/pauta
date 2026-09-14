FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt && useradd --create-home appuser && mkdir /app/data && chown appuser:appuser /app/data
COPY app ./app
COPY static ./static
USER appuser
ENV JOURNAL_DB=/app/data/journal.sqlite3
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--no-access-log"]
