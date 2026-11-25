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
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;600;700&family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
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
</style><link rel="stylesheet" href="/theme.css"></head><body>{{body|safe}}</body></html>"""


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
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;600;700&family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
 :root{--bg:#080d19;--panel:rgba(17,26,45,.78);--panel2:#0c1424;
  --border:rgba(148,163,184,.13);--muted:#91a0b8;--text:#edf3fc;
  --cyan:#55d5d0;--blue:#76a9ff;--amber:#f4bd6a;--rose:#ff8192}
 *{margin:0;padding:0;box-sizing:border-box}
 body{min-height:100vh;padding:34px 24px 70px;color:var(--text);font-family:'DM Sans',sans-serif;
  background:radial-gradient(900px 500px at 8% -8%,rgba(85,213,208,.13),transparent 63%),
   radial-gradient(700px 430px at 100% 5%,rgba(118,169,255,.10),transparent 65%),
   linear-gradient(145deg,#080d19,#0a1020 58%,#080d19)}
 .wrap{max-width:1180px;margin:0 auto}
 .topbar{display:flex;justify-content:space-between;align-items:center;gap:20px;margin-bottom:26px}
 .brand{display:flex;align-items:center;gap:14px}
 .mark{width:46px;height:46px;display:grid;place-items:center;border-radius:15px;
  color:#07131a;background:linear-gradient(145deg,#83e5d4,#50c6c6);
  box-shadow:0 8px 28px rgba(85,213,208,.18)}
 .brand-copy{display:flex;flex-direction:column;gap:3px}
 .eyebrow{color:var(--cyan);font-size:10px;letter-spacing:2.5px;text-transform:uppercase;font-weight:700}
 h1{font-family:'Space Grotesk',sans-serif;font-size:25px;letter-spacing:-.5px}
 .links{display:flex;align-items:center;gap:5px;padding:5px;border:1px solid var(--border);
  border-radius:13px;background:rgba(12,20,36,.75)}
 .links a{font-size:12.5px;font-weight:600;color:var(--muted);padding:9px 12px;
  border-radius:9px;text-decoration:none;transition:.18s}
 .links a:hover{color:var(--text);background:rgba(255,255,255,.05)}
 .links a.home{color:#07131a;background:var(--cyan)}
 .links a.exit{color:#ff9eaa}
 .intro{display:flex;justify-content:space-between;align-items:end;gap:20px;margin:28px 0 18px}
 .intro h2{font-family:'Space Grotesk';font-size:clamp(26px,3vw,36px);letter-spacing:-1px}
 .intro p{color:var(--muted);font-size:14px;margin-top:6px}
 .live{display:inline-flex;align-items:center;gap:8px;color:#b5c4d8;font-size:12px;
  padding:8px 11px;border:1px solid var(--border);border-radius:999px;background:rgba(12,20,36,.6)}
 .live i{width:7px;height:7px;border-radius:50%;background:var(--cyan);box-shadow:0 0 12px var(--cyan)}
 .kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:13px;margin-bottom:18px}
 .kpi{position:relative;overflow:hidden;background:linear-gradient(145deg,rgba(18,29,49,.9),rgba(12,20,36,.82));
  border:1px solid var(--border);border-radius:17px;padding:17px 18px;min-height:103px}
 .kpi:after{content:'';position:absolute;width:90px;height:90px;right:-35px;top:-45px;
  border-radius:50%;background:rgba(85,213,208,.08);filter:blur(2px)}
 .kpi .l{color:var(--muted);font-size:10px;letter-spacing:1.3px;text-transform:uppercase;font-weight:700}
 .kpi .v{font-family:'Space Grotesk';font-size:24px;letter-spacing:-.5px;margin-top:10px}
 .kpi:nth-child(2) .v{color:#b7cbff}.kpi:nth-child(3) .v{color:var(--cyan)}
 .grid{display:grid;grid-template-columns:minmax(320px,.88fr) minmax(0,1.12fr);gap:16px;margin-bottom:16px}
 .card{background:linear-gradient(155deg,rgba(17,27,46,.91),rgba(12,19,34,.88));
  border:1px solid var(--border);border-radius:20px;padding:22px;box-shadow:0 15px 45px rgba(0,0,0,.13)}
 .card-head{display:flex;justify-content:space-between;align-items:start;gap:12px;margin-bottom:17px}
 .card h3{font-family:'Space Grotesk';font-size:17px;letter-spacing:-.2px}
 .desc{color:var(--muted);font-size:12.5px;line-height:1.5;margin-top:5px}
 .cnt{background:rgba(85,213,208,.12);color:var(--cyan);font-size:11px;font-weight:700;
  padding:5px 9px;border:1px solid rgba(85,213,208,.2);border-radius:999px;white-space:nowrap}
 .dropzone{min-height:192px;display:flex;flex-direction:column;align-items:center;justify-content:center;
  text-align:center;border:1px dashed rgba(140,168,192,.36);border-radius:15px;padding:21px;
  background:radial-gradient(240px 130px at 50% 25%,rgba(85,213,208,.08),transparent 80%),rgba(4,10,20,.38);
  cursor:pointer;transition:border-color .2s,background .2s,transform .2s}
 .dropzone:hover,.dropzone.on{border-color:var(--cyan);background-color:rgba(85,213,208,.06);transform:translateY(-1px)}
 .upload-icon{width:43px;height:43px;border-radius:14px;display:grid;place-items:center;
  background:rgba(85,213,208,.12);color:var(--cyan);margin-bottom:11px}
 .drop-title{font-weight:700;font-size:14px}
 .drop-hint{color:var(--muted);font-size:12px;margin-top:5px}
 .choose{display:inline-flex;margin-top:13px;padding:8px 13px;border-radius:9px;
  color:var(--cyan);font-size:12px;font-weight:700;border:1px solid rgba(85,213,208,.28);
  background:rgba(85,213,208,.07)}
 #fileInp{display:none}
 #upStatus{display:none;margin-top:13px;padding:11px 12px;border-radius:10px;
  font-size:12.5px;background:rgba(118,169,255,.08);color:#b7cbff}
 #upStatus.show{display:block}
 #upStatus.ok{color:#8be2c5;background:rgba(85,213,208,.09)}
 #upStatus.bad{color:#ff9eaa;background:rgba(255,129,146,.09)}
 .upload-note{display:flex;align-items:center;gap:8px;color:var(--muted);font-size:11.5px;margin-top:13px}
 .upload-note span{color:var(--cyan)}
 .tools{display:flex;gap:8px;margin-bottom:12px}
 .search{width:100%;padding:9px 11px!important;margin:0!important;border-radius:10px!important;
  background:rgba(4,10,20,.55)!important;font-size:12px!important}
 .oclist{max-height:246px;overflow-y:auto;display:flex;flex-direction:column;gap:8px;padding-right:3px}
 .oc{padding:11px 12px;border:1px solid rgba(148,163,184,.1);border-radius:12px;background:rgba(4,10,20,.35)}
 .oc-top{display:flex;justify-content:space-between;align-items:center;gap:8px;margin-bottom:7px}
 .oc-cat{color:#a6c9ff;background:rgba(118,169,255,.1);padding:4px 8px;border-radius:6px;font-size:10.5px;font-weight:700}
 .oc-date{color:#718098;font-size:10.5px}
 .oc-meta{color:#a5b2c6;font-size:11.5px;margin-bottom:4px}
 .oc-txt{font-size:12.5px;line-height:1.5;color:#dce5f2;overflow-wrap:anywhere}
 .empty{color:var(--muted);text-align:center;padding:32px 14px;font-size:13px}
 .section{margin-top:16px}
 .section-title{display:flex;justify-content:space-between;align-items:end;gap:12px;margin-bottom:13px}
 .section-title h3{font-family:'Space Grotesk';font-size:18px}
 .section-title p{color:var(--muted);font-size:12px;margin-top:4px}
 .table-wrap{overflow:auto;border:1px solid rgba(148,163,184,.1);border-radius:13px}
 table{width:100%;border-collapse:collapse;font-size:12.5px;white-space:nowrap}
 th{color:#718098;font-size:9.5px;text-transform:uppercase;letter-spacing:1.2px;text-align:right;
  padding:11px 13px;border-bottom:1px solid var(--border);background:rgba(4,10,20,.3)}
 th:first-child,td:first-child{text-align:left}
 td{text-align:right;padding:11px 13px;border-bottom:1px solid rgba(148,163,184,.06);color:#b7c3d5}
 tbody tr:hover{background:rgba(85,213,208,.035)}
 tbody tr:last-child td{border-bottom:0}
 td a{color:var(--cyan);text-decoration:none;font-weight:700}
 td a:hover{text-decoration:underline}
 .month-tag{display:inline-flex;align-items:center;gap:7px;color:var(--text);font-weight:600}
 .month-tag i{width:6px;height:6px;border-radius:50%;background:#53647b}
 .month-tag.latest i{background:var(--cyan);box-shadow:0 0 9px rgba(85,213,208,.7)}
 .footer-note{color:#66758b;font-size:11px;text-align:center;margin-top:18px}
 #toast{position:fixed;bottom:24px;left:50%;transform:translate(-50%,80px);opacity:0;transition:.25s;
  background:#101a2b;border:1px solid rgba(85,213,208,.4);border-radius:12px;padding:12px 18px;
  font-size:13px;box-shadow:0 14px 40px rgba(0,0,0,.55);z-index:99;max-width:90vw}
 #toast.show{transform:translate(-50%,0);opacity:1}
 #toast.bad{border-color:rgba(255,129,146,.5)}
 @media(max-width:850px){.grid{grid-template-columns:1fr}.oclist{max-height:300px}}
 @media(max-width:650px){
  body{padding:15px 13px 48px}.topbar{align-items:flex-start;flex-direction:column;gap:13px}
  .links{width:100%;overflow-x:auto}.links a{flex:1;text-align:center;padding:8px 7px;font-size:11px}
  .mark{width:40px;height:40px}.intro{align-items:start;flex-direction:column;gap:12px;margin:22px 0 15px}
  .kpis{grid-template-columns:repeat(2,minmax(0,1fr));gap:9px}.kpi{padding:13px;min-height:91px}
  .kpi .v{font-size:19px}.card{padding:17px 15px;border-radius:16px}
  .grid{gap:12px}.dropzone{min-height:170px}.section-title{align-items:start;flex-direction:column}
 }
 @media(prefers-reduced-motion:reduce){*,*:before,*:after{scroll-behavior:auto!important;transition:none!important;animation:none!important}}
</style><link rel="stylesheet" href="/theme.css"></head><body class="admin-page">
<div class="wrap">
 <div class="topbar">
  <div class="brand"><div class="mark" aria-hidden="true">EP</div>
   <div class="brand-copy"><div class="eyebrow">Elit's Park · Administração</div><h1>Central do condomínio</h1></div>
  </div>
  <div class="links">
   <a class="home" href="/">Painel</a><a href="/historico.html">Histórico</a>
   <a href="/ocorrencia">Nova ocorrência</a><a class="exit" href="/logout">Sair</a>
  </div>
 </div>
 <section class="intro">
  <div><h2>Olá, administrador.</h2><p>Visão geral e tarefas do condomínio em um só lugar.</p></div>
  <div class="live"><i></i> Dados atualizados agora</div>
 </section>
 <div class="kpis" id="kpis"></div>
 <div class="grid">
  <div class="card">
   <div class="card-head"><div><h3>Atualizar balancete</h3>
    <div class="desc">Importe o PDF para atualizar os dados de todos os moradores.</div></div>
    <span class="cnt">PDF</span></div>
   <div id="drop" class="dropzone" role="button" tabindex="0" aria-label="Selecionar ou arrastar PDF">
    <div class="upload-icon" aria-hidden="true">
     <svg width="21" height="21" viewBox="0 0 24 24" fill="none"><path d="M12 16V4m0 0L7.5 8.5M12 4l4.5 4.5M5 15v4a1 1 0 001 1h12a1 1 0 001-1v-4" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/></svg>
    </div>
    <div class="drop-title">Solte o balancete aqui</div>
    <div class="drop-hint">PDF do Condomínio21 · o mês é detectado automaticamente</div>
    <span class="choose">Escolher arquivo</span>
   </div>
   <input type="file" id="fileInp" accept="application/pdf,.pdf">
   <div id="upStatus"></div>
   <div class="upload-note"><span>✓</span> Reenviar um mês substitui os dados anteriores daquele mês.</div>
  </div>
  <div class="card">
   <div class="card-head"><div><h3>Livro de ocorrências</h3>
    <div class="desc">Registros recentes · visíveis somente para administração.</div></div>
    <span class="cnt" id="ocN">0 registros</span></div>
   <div class="tools"><input class="search" type="search" id="ocSearch" placeholder="Filtrar por categoria, unidade ou texto…"></div>
   <div class="oclist" id="ocList"></div>
  </div>
 </div>
 <section class="section">
  <div class="section-title"><div><h3>Balancetes importados</h3>
   <p>Histórico de arquivos que formam a base atual do dashboard.</p></div>
   <span class="cnt" id="monthN"></span></div>
  <div class="table-wrap"><table><thead>
   <tr><th>Mês</th><th>Receitas</th><th>Despesas</th><th>Água</th><th></th></tr>
  </thead><tbody id="tblBody"></tbody></table></div>
 </section>
 <div class="footer-note">Os dados publicados são compartilhados por todos os moradores.</div>
</div>
<div id="toast"></div>
<script>
const BRL = new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL' });
const $ = id => document.getElementById(id);
const esc = s => String(s ?? '').replace(/[&<>"']/g,
  c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
let allOccurrences = [];

function toast(msg, bad) {
  const t = $('toast'); t.textContent = msg;
  t.className = 'show' + (bad ? ' bad' : '');
  clearTimeout(t._h); t._h = setTimeout(() => t.className = '', 4200);
}

async function resumo() {
  const res = await fetch('/api/resumo');
  if (!res.ok) throw new Error('Não foi possível carregar o painel.');
  const r = await res.json();
  const ult = r.meses[r.meses.length - 1] || {};
  $('kpis').innerHTML = `
   <div class="kpi"><div class="l">Meses registrados</div><div class="v">${r.meses.length}</div></div>
   <div class="kpi"><div class="l">Último balancete</div><div class="v">${esc(ult.label || '—')}</div></div>
   <div class="kpi"><div class="l">Água · último mês</div><div class="v">${ult.agua != null ? BRL.format(ult.agua) : '—'}</div></div>
   <div class="kpi"><div class="l">Ocorrências registradas</div><div class="v">${r.ocorrencias.length}</div></div>`;
  allOccurrences = r.ocorrencias;
  $('ocN').textContent = `${r.ocorrencias.length} ${r.ocorrencias.length === 1 ? 'registro' : 'registros'}`;
  $('monthN').textContent = `${r.meses.length} meses`;
  renderOccurrences();
  $('tblBody').innerHTML = r.meses.slice().reverse().map((m, i) => `<tr>
   <td><span class="month-tag ${i === 0 ? 'latest' : ''}"><i></i>${esc(m.label)}</span></td>
   <td>${BRL.format(m.rec)}</td><td>${BRL.format(m.desp)}</td>
   <td>${BRL.format(m.agua)}</td><td><a href="/pdfs/${encodeURIComponent(m.am)}.pdf">Baixar PDF ↗</a></td></tr>`).join('');
}

function renderOccurrences() {
  const q = $('ocSearch').value.trim().toLocaleLowerCase('pt-BR');
  const items = allOccurrences.filter(o =>
    [o.categoria, o.unidade, o.nome, o.texto].join(' ').toLocaleLowerCase('pt-BR').includes(q)
  ).slice(0, 12);
  $('ocList').innerHTML = items.length
    ? items.map(o => `<article class="oc"><div class="oc-top">
       <span class="oc-cat">${esc(o.categoria || 'Outro')}</span><time class="oc-date">${esc(o.criado)}</time></div>
       <div class="oc-meta">${esc(o.unidade || 'Sem unidade')} · ${esc(o.nome || 'Anônimo')}</div>
       <div class="oc-txt">${esc(o.texto)}</div></article>`).join('')
    : `<div class="empty">${q ? 'Nenhuma ocorrência corresponde à busca.' : 'Tudo em dia — nenhuma ocorrência registrada.'}</div>`;
}
resumo().catch(e => toast(e.message, true));
$('ocSearch').addEventListener('input', renderOccurrences);

const drop = $('drop'), fileInp = $('fileInp'), st = $('upStatus');
drop.addEventListener('click', () => fileInp.click());
drop.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); fileInp.click(); } });
['dragover', 'dragenter'].forEach(e => drop.addEventListener(e, ev => { ev.preventDefault(); drop.classList.add('on'); }));
['dragleave', 'drop'].forEach(e => drop.addEventListener(e, ev => { ev.preventDefault(); drop.classList.remove('on'); }));
drop.addEventListener('drop', ev => { const f = ev.dataTransfer.files[0]; if (f) enviar(f); });
fileInp.addEventListener('change', () => { if (fileInp.files[0]) enviar(fileInp.files[0]); });

async function enviar(f) {
  if (f.type !== 'application/pdf' && !f.name.toLowerCase().endsWith('.pdf')) {
    toast('Selecione um arquivo PDF válido.', true); return;
  }
  st.textContent = `Processando ${f.name}…`; st.className = 'show';
  drop.style.pointerEvents = 'none'; drop.style.opacity = '.55';
  try {
    const fd = new FormData(); fd.append('pdf', f);
    const response = await fetch('/upload', { method: 'POST', body: fd });
    const j = await response.json();
    if (!response.ok || !j.ok) throw new Error(j.msg || 'Falha na importação.');
    toast(j.msg, !j.ok);
    st.textContent = `✓ ${j.msg}`; st.className = 'show ok';
    await resumo();
  } catch (e) {
    toast(e.message || 'Falha ao enviar o arquivo.', true);
    st.textContent = e.message || 'Falha ao processar o PDF.'; st.className = 'show bad';
  } finally {
    drop.style.pointerEvents = ''; drop.style.opacity = '';
    fileInp.value = '';
  }
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


@app.get('/theme.css')
def theme_css():
    return send_from_directory(BASE, 'theme.css', mimetype='text/css')


@app.get('/<path:fname>')
@need_login
def static_files(fname):
    if fname in STATIC:
        return send_from_directory(BASE, fname)
    return 'Não encontrado', 404


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000, threaded=True)
