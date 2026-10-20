FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends firefox-esr tzdata \
    && rm -rf /var/lib/apt/lists/*
ENV TZ=Europe/Rome PYTHONUNBUFFERED=1
WORKDIR /app
COPY . .
CMD ["python3", "docker/avvio.py"]
