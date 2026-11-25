FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends poppler-utils \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir flask gunicorn

WORKDIR /app
COPY extrair.py app.py index.html historico.html senha.js ./
COPY pdfs /seed/pdfs
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENV DATA_DIR=/data
VOLUME /data
EXPOSE 8000

ENTRYPOINT ["/entrypoint.sh"]
