FROM alpine:3.22
RUN apk add --no-cache python3 firefox-esr tzdata ca-certificates font-dejavu \
    && ln -s /usr/bin/firefox-esr /usr/local/bin/firefox
# Politica TLS di Fedora (vedi docker/openssl.cnf): senza, Subito.it risponde 403
COPY docker/openssl.cnf /etc/ssl/openssl-policy.cnf
ENV TZ=Europe/Rome PYTHONUNBUFFERED=1 OPENSSL_CONF=/etc/ssl/openssl-policy.cnf \
    SSL_CIPHERS="@SECLEVEL=2:kEECDH:kRSA:kEDH:kPSK:kDHEPSK:kECDHEPSK:kRSAPSK:-aDSS:-3DES:!DES:!RC4:!RC2:!IDEA:-SEED:!eNULL:!aNULL:!MD5:-SHA384:-CAMELLIA:-ARIA:-AESCCM8"
WORKDIR /app
COPY agents ./agents
COPY docker ./docker
COPY web ./web
COPY run.py server.py config.example.json ./
EXPOSE 8765
CMD ["python3", "docker/avvio.py"]
