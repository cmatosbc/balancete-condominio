"""
Servidor do dashboard — dois níveis de acesso:

  morador: vê index/histórico e simula o próprio boleto
  admin:   idem + sobe o PDF do balancete (vira base para todos)

Variáveis de ambiente obrigatórias:
  ADMIN_PASSWORD, MORADOR_PASSWORD   (SECRET_KEY opcional — sessões)

Dev:   python3 app.py
Prod:  gunicorn -b 0.0.0.0:8000 -w 2 app:app
"""
import hmac
import os
import secrets
import urllib.parse
from functools import wraps
from pathlib import Path

from flask import (Flask, redirect, render_template_string, request,
                   send_from_directory, session)

import extrair

BASE = Path(__file__).parent
DATA_DIR = extrair.DATA_DIR
STATIC = ('index.html', 'historico.html', 'senha.js')


def _secret_key():
    """Chave da sessão: env, ou gerada uma vez e persistida no volume
    (estável entre workers do gunicorn e entre restarts)."""
    if os.environ.get('SECRET_KEY'):
        return os.environ['SECRET_KEY']
    DATA_DIR.mkdir(exist_ok=True)
    f = DATA_DIR / '.secret_key'
    if f.exists():
        return f.read_text().strip()
    key = secrets.token_hex(32)
    f.write_text(key)
    os.chmod(f, 0o600)
    return key


app = Flask(__name__)
app.secret_key = _secret_key()
ADMIN_PW = os.environ.get('ADMIN_PASSWORD', '')
MORADOR_PW = os.environ.get('MORADOR_PASSWORD', '')
if not ADMIN_PW or not MORADOR_PW:
    raise SystemExit('Defina ADMIN_PASSWORD e MORADOR_PASSWORD no ambiente.')

PAGE = """<!DOCTYPE html><html lang="pt-BR"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow"><title>{{titulo}}</title>
<style>
 body{background:radial-gradient(1100px 600px at 15% -10%,rgba(56,189,248,.10),transparent 60%),#070c1a;
      color:#e8edf6;font-family:Inter,system-ui,sans-serif;min-height:100vh;display:flex;
      align-items:center;justify-content:center;padding:20px;margin:0}
 .card{background:rgba(15,23,42,.78);border:1px solid rgba(148,163,184,.14);border-radius:22px;
       padding:36px 32px;max-width:400px;width:100%;backdrop-filter:blur(10px);
       box-shadow:0 24px 60px rgba(0,0,0,.5)}
 .wide{max-width:720px}
 .eyebrow{color:#7dd3fc;font-size:11px;letter-spacing:3px;text-transform:uppercase;
          font-weight:600;margin:12px 0 6px}
 h1{font-family:'Space Grotesk',sans-serif;font-size:22px;margin:0 0 6px}
 .mut{color:#8a94a8;font-size:13px;margin-bottom:20px}
 input[type=password],input[type=file]{width:100%;padding:12px 14px;border-radius:10px;
  border:1px solid rgba(148,163,184,.22);background:rgba(2,6,23,.65);color:#e8edf6;
  font-size:15px;outline:none;box-sizing:border-box}
 button{margin-top:16px;width:100%;padding:12px;border-radius:10px;border:none;
  background:linear-gradient(135deg,#38bdf8,#818cf8);color:#0b1220;font-weight:700;
  font-size:14px;cursor:pointer}
 .err{color:#fb7185;font-size:12.5px;margin-top:8px}
 .ok{color:#34d399;font-size:13px;margin:0 0 14px;padding:10px 12px;
   background:rgba(52,211,153,.08);border:1px solid rgba(52,211,153,.3);border-radius:10px}
 .bad{color:#fb7185;font-size:13px;margin:0 0 14px;padding:10px 12px;
   background:rgba(251,113,133,.08);border:1px solid rgba(251,113,133,.3);border-radius:10px}
 table{width:100%;border-collapse:collapse;font-size:13.5px;margin-top:14px}
 th{color:#8a94a8;font-size:11px;text-transform:uppercase;letter-spacing:1px;
    text-align:left;padding:8px 10px;border-bottom:1px solid rgba(148,163,184,.14)}
 td{padding:9px 10px;border-bottom:1px solid rgba(148,163,184,.06)}
 td:last-child,th:last-child{text-align:right}
 a{color:#38bdf8;text-decoration:none} a:hover{text-decoration:underline}
 .links{margin-top:20px;display:flex;justify-content:space-between;font-size:13px}
</style></head><body>{{body|safe}}</body></html>"""


def role():
    return session.get('role')


def need_login(f):
    @wraps(f)
    def w(*a, **kw):
        return f(*a, **kw) if role() else redirect('/login')
    return w


def need_admin(f):
    @wraps(f)
    def w(*a, **kw):
        if not role():
            return redirect('/login')
        if role() != 'admin':
            return render_template_string(
                PAGE, titulo='Sem permissão',
                body='<div class="card"><h1>⛔ Área restrita</h1>'
                     '<p class="mut">Somente o administrador pode acessar.</p>'
                     '<div class="links"><a href="/">← Dashboard</a>'
                     '<a href="/logout">Sair</a></div></div>'), 403
        return f(*a, **kw)
    return w


@app.get('/login')
def login():
    if role():
        return redirect('/')
    return render_template_string(
        PAGE, titulo='Entrar',
        body='<form class="card" method="post" action="/login">'
             '<div style="font-size:34px;text-align:center">🔒</div>'
             '<div class="eyebrow" style="text-align:center">Condomínio Elit\'s Park</div>'
             '<h1 style="text-align:center">Área dos condôminos</h1>'
             '<p class="mut" style="text-align:center">Senha de condômino ou de administrador</p>'
             f'{"<p class=err>Senha incorreta — tente novamente</p>" if request.args.get("e") else ""}'
             '<input type="password" name="senha" placeholder="Senha" autofocus '
             'autocomplete="current-password">'
             '<button type="submit">Entrar</button></form>')


@app.post('/login')
def do_login():
    pw = request.form.get('senha', '')
    r = 'admin' if hmac.compare_digest(pw, ADMIN_PW) else \
        'morador' if hmac.compare_digest(pw, MORADOR_PW) else None
    if not r:
        return redirect('/login?e=1')
    session['role'] = r
    resp = redirect('/')
    # cookies-hint: senha.js não bloqueia quem já logou; nav mostra link Admin
    resp.set_cookie('cond_app', '1')
    resp.set_cookie('cond_role', r)
    return resp


@app.get('/logout')
def logout():
    session.clear()
    resp = redirect('/login')
    resp.delete_cookie('cond_app')
    resp.delete_cookie('cond_role')
    return resp


@app.get('/')
@need_login
def index():
    return send_from_directory(BASE, 'index.html')


@app.get('/admin')
@need_admin
def admin():
    meses = extrair.db_conn().execute(
        'SELECT ano_mes, mes_label, agua FROM meses ORDER BY ano_mes').fetchall()
    linhas = ''.join(
        f'<tr><td>{ml}</td><td>{am}</td><td>R$ {ag:,.2f}</td>'
        f'<td><a href="/pdfs/{am}.pdf">pdf</a></td></tr>'
        for am, ml, ag in meses)
    ok = request.args.get('ok')
    erro = request.args.get('erro')
    msg = f'<p class="ok">✓ {ok}</p>' if ok else \
          f'<p class="bad">⚠ {erro}</p>' if erro else ''
    return render_template_string(
        PAGE, titulo='Admin',
        body=f'<div class="card wide"><div class="eyebrow">Administração</div>'
             f'<h1>Subir balancete</h1>'
             f'<p class="mut">O PDF vira a base de dados para todos os condôminos.</p>{msg}'
             f'<form method="post" action="/upload" enctype="multipart/form-data">'
             f'<input type="file" name="pdf" accept=".pdf" required>'
             f'<button type="submit">Importar</button></form>'
             f'<table><tr><th>Mês</th><th>Chave</th><th>Água</th><th></th></tr>{linhas}</table>'
             f'<div class="links"><a href="/">← Dashboard</a>'
             f'<a href="/historico.html">Histórico</a><a href="/logout">Sair</a></div></div>')


@app.post('/upload')
@need_admin
def upload():
    f = request.files.get('pdf')
    if not f or not f.filename.lower().endswith('.pdf'):
        return redirect('/admin?erro=' + urllib.parse.quote('Envie um arquivo PDF'))
    tmp = DATA_DIR / '_upload.pdf'
    DATA_DIR.mkdir(exist_ok=True)
    f.save(tmp)
    try:
        conn = extrair.db_conn()
        dados, avisos = extrair.parse_pdf(tmp)
        am = extrair.db_upsert(conn, dados)
        extrair.archive_pdf(tmp, am)
        extrair.regenerate_js(conn)
        msg = f'{dados.get("mesLabel", "?")} [{am}] registrado'
        if avisos:
            msg += f' — ⚠ {"; ".join(avisos)}'
        return redirect('/admin?ok=' + urllib.parse.quote(msg))
    except Exception as e:
        return redirect('/admin?erro=' + urllib.parse.quote(f'Falha ao processar: {e}'))
    finally:
        tmp.unlink(missing_ok=True)


@app.get('/pdfs/<nome>')
@need_admin
def pdf(nome):
    return send_from_directory(extrair.PDFS, nome)


@app.get('/dados.js')
@need_login
def dadosjs():
    return send_from_directory(DATA_DIR, 'dados.js', mimetype='application/javascript')


@app.get('/<path:fname>')
@need_login
def static_files(fname):
    if fname in STATIC:
        return send_from_directory(BASE, fname)
    return 'Não encontrado', 404


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000, threaded=True)
