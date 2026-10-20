FROM alpine:3.22
RUN apk add --no-cache python3 firefox-esr tzdata ca-certificates font-dejavu \
    && ln -s /usr/bin/firefox-esr /usr/local/bin/firefox
ENV TZ=Europe/Rome PYTHONUNBUFFERED=1
WORKDIR /app
COPY agents ./agents
COPY docker ./docker
COPY web ./web
COPY run.py server.py config.example.json ./
EXPOSE 8765
CMD ["python3", "docker/avvio.py"]
