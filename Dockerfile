# ---------- estágio 1: assets (Tailwind + Preline) ----------
FROM node:20-alpine AS assets
WORKDIR /build
COPY package.json package-lock.json tailwind.config.js ./
RUN npm ci --no-audit --no-fund
COPY src ./src
COPY templates ./templates
COPY index.html historico.html ./
COPY static/js ./static/js
RUN npx tailwindcss -i src/input.css -o static/css/theme.css --minify \
 && mkdir -p static/vendor \
 && cp node_modules/preline/dist/preline.js static/vendor/preline.js

# ---------- estágio 2: runtime (sem Node em produção) ----------
FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends poppler-utils \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir flask gunicorn

WORKDIR /app
COPY extrair.py app.py index.html historico.html senha.js ./
COPY templates ./templates
COPY --from=assets /build/static ./static
COPY pdfs /seed/pdfs
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENV DATA_DIR=/data
VOLUME /data
EXPOSE 8000

ENTRYPOINT ["/entrypoint.sh"]
