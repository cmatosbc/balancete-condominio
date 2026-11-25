#!/bin/sh
set -e
mkdir -p "$DATA_DIR"

# primeiro boot: semeia o banco a partir dos PDFs embutidos na imagem
if [ ! -f "$DATA_DIR/balancetes.db" ] && [ -d /seed/pdfs ]; then
  python3 extrair.py /seed/pdfs
fi
# garante dados.js mesmo se o volume já tinha banco
[ -f "$DATA_DIR/dados.js" ] || python3 -c "import extrair; extrair.regenerate_js(extrair.db_conn())"

exec gunicorn -b 0.0.0.0:8000 -w 2 app:app
