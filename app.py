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
from markupsafe import escape

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
 input[type=password],input[type=file],input[type=text],select,textarea{
  width:100%;padding:12px 14px;border-radius:10px;
  border:1px solid rgba(148,163,184,.22);background:rgba(2,6,23,.65);color:#e8edf6;
  font-size:15px;outline:none;box-sizing:border-box;font-family:inherit;margin-bottom:12px}
 textarea{min-height:110px;resize:vertical}
 label{display:block;color:#8a94a8;font-size:12px;margin:0 0 4px;text-transform:uppercase;letter-spacing:1px}
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


ADMIN_HTML = """<!DOCTYPE html><html lang="pt-BR"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow"><title>Admin · Elit's Park</title>
<style>
 :root{--border:rgba(148,163,184,.14);--muted:#8a94a8}
 *{margin:0;padding:0;box-sizing:border-box}
 body{background:radial-gradient(1100px 600px at 15% -10%,rgba(56,189,248,.10),transparent 60%),#070c1a;
      color:#e8edf6;font-family:Inter,system-ui,sans-serif;min-height:100vh;padding:36px 20px 60px}
 .wrap{max-width:980px;margin:0 auto}
 .topbar{display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:26px}
 .links{display:flex;gap:8px;flex-wrap:wrap}
 .links a{font-size:13px;font-weight:600;color:var(--muted);padding:7px 13px;border-radius:9px;
  border:1px solid var(--border);text-decoration:none}
 .links a:hover{color:#e8edf6;border-color:rgba(56,189,248,.4)}
 .links a.home{color:#7dd3fc;border-color:rgba(56,189,248,.35)}
 .eyebrow{color:#7dd3fc;font-size:11px;letter-spacing:3px;text-transform:uppercase;font-weight:600;margin-bottom:6px}
 h1{font-family:'Space Grotesk',sans-serif;font-size:26px}
 .sub{color:var(--muted);font-size:13.5px;margin-top:4px}
 .kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:14px;margin:22px 0 20px}
 .kpi{background:rgba(15,23,42,.6);border:1px solid var(--border);border-radius:16px;padding:16px 18px;backdrop-filter:blur(8px)}
 .kpi .l{color:var(--muted);font-size:11px;letter-spacing:1.4px;text-transform:uppercase;font-weight:600}
 .kpi .v{font-family:'Space Grotesk';font-size:23px;margin-top:7px}
 .grid{display:grid;grid-template-columns:1fr 1.15fr;gap:18px;margin-bottom:18px}
 @media(max-width:860px){.grid{grid-template-columns:1fr}}
 .card{background:rgba(15,23,42,.6);border:1px solid var(--border);border-radius:20px;
       padding:22px 24px;backdrop-filter:blur(8px)}
 .card h2{font-family:'Space Grotesk';font-size:18px;margin-bottom:4px;display:flex;align-items:center;gap:8px}
 .card .desc{color:var(--muted);font-size:13px;margin-bottom:16px}
 .cnt{background:rgba(56,189,248,.15);color:#7dd3fc;font-size:12px;font-weight:700;
      padding:2px 10px;border-radius:999px}
 #drop{border:1.5px dashed rgba(148,163,184,.3);border-radius:14px;padding:30px 16px;text-align:center;
   color:var(--muted);font-size:13.5px;cursor:pointer;transition:.15s;background:rgba(2,6,23,.35)}
 #drop:hover,#drop.on{border-color:#38bdf8;color:#7dd3fc;background:rgba(56,189,248,.06)}
 #drop b{color:#e8edf6;font-weight:600}
 #upStatus{margin-top:12px;font-size:13px;min-height:18px}
 .proc{color:#7dd3fc}
 .ok{color:#34d399}.bad{color:#fb7185}
 .oclist{max-height:330px;overflow-y:auto;display:flex;flex-direction:column;gap:10px;padding-right:4px}
 .oc{background:rgba(2,6,23,.5);border:1px solid var(--border);border-radius:12px;padding:11px 14px}
 .oc .top{display:flex;justify-content:space-between;gap:8px;font-size:11.5px;color:var(--muted);margin-bottom:5px;flex-wrap:wrap}
 .oc .cat{color:#7dd3fc;font-weight:600}
 .oc .quem{color:#aeb9cf}
 .oc .txt{font-size:13.5px;line-height:1.5;color:#d7deeb}
 table{width:100%;border-collapse:collapse;font-size:13.5px}
 th{color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:1px;text-align:right;
    padding:8px 10px;border-bottom:1px solid var(--border)}
 th:first-child,td:first-child{text-align:left}
 td{text-align:right;padding:10px;border-bottom:1px solid rgba(148,163,184,.06)}
 td a{color:#38bdf8;text-decoration:none;font-weight:600}
 #toast{position:fixed;bottom:24px;left:50%;transform:translate(-50%,80px);opacity:0;transition:.25s;
  background:#0d1424;border:1px solid rgba(56,189,248,.4);border-radius:12px;padding:12px 20px;
  font-size:13.5px;box-shadow:0 14px 40px rgba(0,0,0,.6);z-index:99;max-width:90vw}
 #toast.show{transform:translate(-50%,0);opacity:1}
 #toast.bad{border-color:rgba(251,113,133,.5)}
 @media(max-width:760px){
  body{padding:0 14px 60px}
  .topbar{position:sticky;top:0;z-index:60;margin:0 -14px 20px;padding:10px 14px;
   background:rgba(7,12,26,.94);backdrop-filter:blur(12px);border-bottom:1px solid var(--border)}
 }
</style></head><body>
<div class="wrap">
 <div class="topbar">
  <div><div class="eyebrow">Condomínio Elit's Park</div><h1>Painel do administrador</h1>
   <div class="sub">Upload de balancetes · livro de ocorrências</div></div>
  <div class="links">
   <a class="home" href="/">Dashboard</a><a href="/historico.html">Histórico</a>
   <a href="/ocorrencia">Ocorrência</a><a href="/logout">Sair 🔒</a>
  </div>
 </div>
 <div class="kpis" id="kpis"></div>
 <div class="grid">
  <div class="card">
   <h2>📤 Subir balancete</h2>
   <div class="desc">O PDF vira a base de dados para todos os condôminos.</div>
   <div id="drop"><b>Arraste o PDF</b> aqui<br>ou <u>clique para escolher</u></div>
   <input type="file" id="fileInp" accept=".pdf" hidden>
   <div id="upStatus"></div>
  </div>
  <div class="card">
   <h2>📖 Livro de ocorrências <span class="cnt" id="ocN"></span></h2>
   <div class="desc">Visível somente para você.</div>
   <div class="oclist" id="ocList"></div>
  </div>
 </div>
 <div class="card">
  <h2>Meses no banco</h2>
  <div class="desc">Clique em "pdf" para baixar o original.</div>
  <div style="overflow-x:auto"><table><thead>
   <tr><th>Mês</th><th>Receitas</th><th>Despesas</th><th>Água</th><th></th></tr>
  </thead><tbody id="tblBody"></tbody></table></div>
 </div>
</div>
<div id="toast"></div>
<script>
const BRL = new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL' });
const $ = id => document.getElementById(id);
const esc = s => String(s ?? '').replace(/[&<>"']/g,
  c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

function toast(msg, bad) {
  const t = $('toast'); t.textContent = msg;
  t.className = 'show' + (bad ? ' bad' : '');
  clearTimeout(t._h); t._h = setTimeout(() => t.className = '', 4200);
}

async function resumo() {
  const r = await (await fetch('/api/resumo')).json();
  const ult = r.meses[r.meses.length - 1] || {};
  $('kpis').innerHTML = `
   <div class="kpi"><div class="l">Meses no banco</div><div class="v">${r.meses.length}</div></div>
   <div class="kpi"><div class="l">Último mês</div><div class="v">${esc(ult.label || '—')}</div></div>
   <div class="kpi"><div class="l">Água (último)</div><div class="v">${ult.agua != null ? BRL.format(ult.agua) : '—'}</div></div>
   <div class="kpi"><div class="l">Ocorrências</div><div class="v">${r.ocorrencias.length}</div></div>`;
  $('ocN').textContent = r.ocorrencias.length;
  $('ocList').innerHTML = r.ocorrencias.length
    ? r.ocorrencias.map(o => `<div class="oc"><div class="top">
       <span class="cat">${esc(o.categoria)}</span><span>${esc(o.criado)}</span></div>
       <div class="quem">${esc(o.unidade || '—')} · ${esc(o.nome || 'anônimo')}</div>
       <div class="txt">${esc(o.texto)}</div></div>`).join('')
    : '<div class="desc" style="margin:0">Nenhuma ocorrência registrada ainda.</div>';
  $('tblBody').innerHTML = r.meses.map(m => `<tr>
   <td><b>${esc(m.label)}</b></td><td>${BRL.format(m.rec)}</td><td>${BRL.format(m.desp)}</td>
   <td><b>${BRL.format(m.agua)}</b></td><td><a href="/pdfs/${m.am}.pdf">pdf</a></td></tr>`).join('');
}
resumo();

const drop = $('drop'), fileInp = $('fileInp'), st = $('upStatus');
drop.addEventListener('click', () => fileInp.click());
['dragover', 'dragenter'].forEach(e => drop.addEventListener(e, ev => { ev.preventDefault(); drop.classList.add('on'); }));
['dragleave', 'drop'].forEach(e => drop.addEventListener(e, ev => { ev.preventDefault(); drop.classList.remove('on'); }));
drop.addEventListener('drop', ev => { const f = ev.dataTransfer.files[0]; if (f) enviar(f); });
fileInp.addEventListener('change', () => { if (fileInp.files[0]) enviar(fileInp.files[0]); });

async function enviar(f) {
  if (!f.name.toLowerCase().endsWith('.pdf')) { toast('Envie um arquivo PDF', true); return; }
  st.textContent = `Processando ${f.name}…`; st.className = 'proc';
  try {
    const fd = new FormData(); fd.append('pdf', f);
    const j = await (await fetch('/upload', { method: 'POST', body: fd })).json();
    toast(j.msg, !j.ok);
  } catch (e) { toast('Falha ao enviar: ' + e, true); }
  st.textContent = ''; st.className = '';
  fileInp.value = '';
  resumo();
}
</script></body></html>"""


@app.get('/admin')
@need_admin
def admin():
    return ADMIN_HTML


@app.get('/api/resumo')
@need_admin
def api_resumo():
    meses = extrair.db_conn().execute(
        'SELECT ano_mes, mes_label, receitas, despesas, agua '
        'FROM meses ORDER BY ano_mes').fetchall()
    ocs = odb().execute(
        'SELECT criado_em, unidade, nome, categoria, texto '
        'FROM ocorrencias ORDER BY id DESC LIMIT 60').fetchall()
    return {
        'meses': [{'am': a, 'label': l, 'rec': r, 'desp': d, 'agua': g}
                  for a, l, r, d, g in meses],
        'ocorrencias': [{'criado': c, 'unidade': u, 'nome': n,
                         'categoria': cat, 'texto': t} for c, u, n, cat, t in ocs]}


@app.post('/upload')
@need_admin
def upload():
    f = request.files.get('pdf')
    if not f or not f.filename.lower().endswith('.pdf'):
        return {'ok': False, 'msg': 'Envie um arquivo PDF'}, 400
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
        return {'ok': True, 'msg': msg}
    except Exception as e:
        return {'ok': False, 'msg': f'Falha ao processar: {e}'}, 500
    finally:
        tmp.unlink(missing_ok=True)


@app.get('/pdfs/<nome>')
@need_admin
def pdf(nome):
    return send_from_directory(extrair.PDFS, nome)


# ---------------- livro de ocorrências ----------------

CATEGORIAS = ['Barulho', 'Vazamento / infiltração', 'Manutenção', 'Limpeza',
              'Segurança', 'Elevador', 'Estacionamento / garagem', 'Animais', 'Outro']


def odb():
    conn = extrair.db_conn()
    conn.execute("""CREATE TABLE IF NOT EXISTS ocorrencias(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        criado_em TEXT DEFAULT (datetime('now','localtime')),
        unidade TEXT, nome TEXT, categoria TEXT, texto TEXT NOT NULL)""")
    return conn


@app.route('/ocorrencia', methods=['GET', 'POST'])
@need_login
def ocorrencia():
    """Qualquer papel logado pode registrar; só admin vê a lista."""
    if request.method == 'POST':
        texto = request.form.get('texto', '').strip()
        if not texto:
            return redirect('/ocorrencia?erro=' + urllib.parse.quote(
                'Descreva a ocorrência antes de enviar'))
        conn = odb()
        conn.execute(
            'INSERT INTO ocorrencias(unidade, nome, categoria, texto) VALUES (?,?,?,?)',
            (request.form.get('unidade', '').strip() or None,
             request.form.get('nome', '').strip() or None,
             request.form.get('categoria') if request.form.get('categoria') in CATEGORIAS else 'Outro',
             texto))
        conn.commit()
        return redirect('/ocorrencia?ok=1')

    ok = '<p class="ok">✓ Ocorrência registrada — a administração foi notificada.</p>' \
        if request.args.get('ok') else ''
    erro = f'<p class="bad">⚠ {escape(request.args.get("erro", ""))}</p>' \
        if request.args.get('erro') else ''
    cats = ''.join(f'<option>{c}</option>' for c in CATEGORIAS)
    return render_template_string(
        PAGE, titulo='Ocorrência',
        body=f'<div class="card"><div class="eyebrow">Livro de ocorrências</div>'
             f'<h1>Registrar ocorrência</h1>'
             f'<p class="mut">Vai direto para a administração — outros condôminos não veem.</p>'
             f'{ok}{erro}'
             f'<form method="post">'
             f'<label>Unidade (opcional)</label>'
             f'<input type="text" name="unidade" placeholder="Ex.: A3-11">'
             f'<label>Seu nome (opcional)</label>'
             f'<input type="text" name="nome" placeholder="Anônimo se vazio">'
             f'<label>Categoria</label><select name="categoria">{cats}</select>'
             f'<label>Ocorrência</label>'
             f'<textarea name="texto" required '
             f'placeholder="Descreva o que aconteceu, onde e quando"></textarea>'
             f'<button type="submit">Registrar</button></form>'
             f'<div class="links"><a href="/">← Dashboard</a>'
             f'<a href="/logout">Sair</a></div></div>')


@app.get('/admin/ocorrencias')
@need_admin
def admin_ocorrencias():
    return redirect('/admin')


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
