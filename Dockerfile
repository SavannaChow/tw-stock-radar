FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    RADAR_HOST=0.0.0.0 \
    RADAR_PORT=8899 \
    RADAR_OPEN_BROWSER=0 \
    RADAR_DATA_DIR=/app/data

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN mkdir -p /app/cache /app/twdata /app/data

EXPOSE 8899

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8899/', timeout=3)" || exit 1

CMD ["python", "-u", "app.py"]
