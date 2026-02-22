FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY tracker/ tracker/
COPY config.yaml .

ENV PYTHONUNBUFFERED=1

CMD ["python", "-m", "tracker"]
