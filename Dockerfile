FROM nginx:alpine

# Site estático: dados.js é regenerado pelo extrair.py (git/CI) antes do build.
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY index.html historico.html dados.js senha.js /usr/share/nginx/html/

EXPOSE 80
