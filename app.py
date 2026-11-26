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
 .ugrid{display:grid;grid-template-columns:1fr 1fr;gap:10px}
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
 .oc-right{display:flex;align-items:center;gap:7px}
 .oc-btn{border:1px solid rgba(85,213,208,.3);background:rgba(85,213,208,.07);color:var(--cyan);
  border-radius:7px;font-size:10.5px;font-weight:700;padding:4px 9px;cursor:pointer;transition:.15s;white-space:nowrap}
 .oc-btn:hover{background:rgba(85,213,208,.18)}
 .oc.done{opacity:.48}
 .oc.done .oc-txt{text-decoration:line-through}
 .oc.done .oc-cat{background:rgba(52,211,153,.12);color:#8be2c5}
 .oc.done .oc-btn{border-color:rgba(148,163,184,.3);color:var(--muted);background:rgba(148,163,184,.06)}
 .prop-grid{display:grid;grid-template-columns:minmax(280px,.7fr) minmax(0,1.3fr);gap:16px;align-items:start}
 .prop-form input[type=text],.prop-form textarea{width:100%;padding:10px 12px;border-radius:10px;
  border:1px solid var(--border);background:rgba(4,10,20,.55);color:var(--text);
  font-family:inherit;font-size:13px;margin-bottom:10px;outline:none;resize:vertical}
 .prop-form input:focus,.prop-form textarea:focus{border-color:var(--cyan)}
 .prop-form button{width:100%;padding:11px;border:none;border-radius:10px;font-weight:700;
  font-size:13px;cursor:pointer;color:#07131a;background:linear-gradient(135deg,#83e5d4,#50c6c6);transition:.15s}
 .prop-form button:hover{filter:brightness(1.08)}
 .prop-list{display:flex;flex-direction:column;gap:10px;max-height:340px;overflow-y:auto;padding-right:3px}
 .prop{padding:13px 14px;border:1px solid rgba(148,163,184,.1);border-radius:13px;background:rgba(4,10,20,.35)}
 .prop-top{display:flex;justify-content:space-between;align-items:center;gap:8px;margin-bottom:7px}
 .pstate{font-size:9.5px;font-weight:700;padding:4px 8px;border-radius:6px;letter-spacing:.7px;text-transform:uppercase}
 .pstate.open{color:#8be2c5;background:rgba(85,213,208,.12);border:1px solid rgba(85,213,208,.25)}
 .pstate.closed{color:#a5b2c6;background:rgba(148,163,184,.1);border:1px solid rgba(148,163,184,.18)}
 .ptit{font-family:'Space Grotesk';font-size:14.5px;margin:0 0 4px}
 .pdesc{color:var(--muted);font-size:12px;line-height:1.5;overflow-wrap:anywhere}
 .vbar{display:flex;height:8px;border-radius:99px;overflow:hidden;background:rgba(148,163,184,.12);margin:11px 0 6px}
 .vbar .f{background:#34d399}.vbar .c{background:#fb7185}.vbar .f,.vbar .c{transition:width .4s}
 .vnums{display:flex;justify-content:space-between;font-size:11px;color:#a5b2c6}
 .vnums .fv{color:#34d399;font-weight:700}.vnums .ct{color:#fb7185;font-weight:700}
 .pbtn{margin-top:10px;padding:6px 11px;border-radius:8px;font-size:11px;font-weight:700;cursor:pointer;
  border:1px solid rgba(148,163,184,.3);background:transparent;color:var(--muted);transition:.15s}
 .pbtn:hover{color:var(--text);border-color:rgba(148,163,184,.55)}
 .blocks{display:grid;grid-template-columns:repeat(6,1fr);gap:10px}
 .block{border:1px solid var(--border);border-radius:14px;padding:11px;background:rgba(4,10,20,.35)}
 .bname{font-family:'Space Grotesk';font-size:12px;font-weight:700;color:var(--cyan);
  text-align:center;margin-bottom:9px;letter-spacing:1.5px}
 .bgrid{display:grid;grid-template-columns:repeat(4,1fr);gap:5px}
 .apt{position:relative;aspect-ratio:1;display:grid;place-items:center;border-radius:6px;padding:0;
  border:1px solid rgba(148,163,184,.14);background:rgba(17,27,46,.6);
  color:#b7c3d5;font-size:10px;font-weight:600;cursor:pointer;transition:.15s;font-family:inherit}
 .apt:hover{border-color:var(--cyan);transform:scale(1.08)}
 .apt.late{background:rgba(251,113,133,.22);border-color:rgba(251,113,133,.6);color:#ffc2ca}
 .apt.sel{outline:2px solid var(--cyan);outline-offset:1px}
 .dots{position:absolute;bottom:2px;left:50%;transform:translateX(-50%);display:flex;gap:2px}
 .dots i{width:4px;height:4px;border-radius:50%}
 .din{background:#34d399}.dout{background:#fb923c}.did{background:#c084fc}
 .ocb{position:absolute;top:-5px;right:-5px;min-width:14px;height:14px;padding:0 3px;border-radius:7px;
  background:#f4bd6a;color:#231a05;font-size:8.5px;font-weight:800;display:grid;place-items:center}
 .legend{display:flex;flex-wrap:wrap;gap:14px;margin-top:13px;font-size:11px;color:var(--muted)}
 .lg{width:9px;height:9px;border-radius:3px;display:inline-block;margin-right:5px;vertical-align:-1px}
 .lg.late{background:rgba(251,113,133,.7)}.lg.din{background:#34d399}.lg.dout{background:#fb923c}
 .lg.did{background:#c084fc}.lg.docb{background:#f4bd6a;border-radius:50%}
 .upanel{margin-top:14px;border:1px solid rgba(85,213,208,.3);border-radius:15px;padding:15px 16px;
  background:linear-gradient(155deg,rgba(17,27,46,.95),rgba(12,19,34,.9))}
 .up-head{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:12px}
 .up-head h3{font-family:'Space Grotesk';font-size:17px}
 .up-sub{color:var(--muted);font-size:11px;margin-top:3px}
 .up-close{background:none;border:none;color:var(--muted);font-size:20px;cursor:pointer;padding:0 4px;line-height:1}
 .up-close:hover{color:var(--text)}
 .up-flags{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:8px}
 .uflag{display:flex;align-items:center;gap:8px;font-size:12.5px;color:#b7c3d5;cursor:pointer;
  padding:9px 10px;border:1px solid var(--border);border-radius:10px;background:rgba(4,10,20,.4)}
 .uflag input{accent-color:var(--cyan);width:15px;height:15px;cursor:pointer}
 .up-ocs{margin-top:12px;font-size:12px;color:var(--muted)}
 .up-ocs-t{font-size:10px;letter-spacing:1px;text-transform:uppercase;font-weight:700;margin-bottom:7px;color:#a5b2c6}
 .up-oc{padding:7px 0;border-bottom:1px solid rgba(148,163,184,.08);font-size:12px;color:#dce5f2}
 .up-oc:last-child{border-bottom:0}
 .b-tot{color:#66758b;font-size:9.5px;text-align:center;margin-top:8px}
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
 @media(max-width:850px){.grid{grid-template-columns:1fr}.oclist{max-height:300px}
 .prop-grid{grid-template-columns:1fr}.prop-list{max-height:400px}
 .blocks{grid-template-columns:repeat(3,1fr)}}
@media(max-width:480px){.blocks{grid-template-columns:repeat(2,1fr)}}
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
   <a href="/ocorrencia">Nova ocorrência</a><a href="/propostas">Votações</a>
   <a class="exit" href="/logout">Sair</a>
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
  <div class="section-title"><div><h3>Propostas & votações</h3>
   <p>Publique ideias e obras para os moradores votarem — um voto por unidade.</p></div>
   <span class="cnt" id="propN"></span></div>
  <div class="prop-grid">
   <form class="card prop-form" id="propForm">
    <input type="text" id="propTitulo" placeholder="Título — ex.: Pintura da fachada" required maxlength="120">
    <textarea id="propDesc" rows="5" placeholder="Detalhes: custo estimado, prazo, benefícios…"></textarea>
    <button type="submit">Publicar para votação</button>
   </form>
   <div class="prop-list" id="propList"></div>
  </div>
 </section>
 <section class="section">
  <div class="section-title"><div><h3>Desenho predial</h3>
   <p>Toque em uma unidade para marcar/desmarcar atraso — unidades em atraso não votam.</p></div>
   <span class="cnt" id="lateN"></span></div>
  <div class="blocks" id="blocks"></div>
  <div class="legend">
   <span><i class="lg late"></i>Em atraso</span>
   <span><i class="lg din"></i>Mudança · entrada</span>
   <span><i class="lg dout"></i>Mudança · saída</span>
   <span><i class="lg did"></i>Idoso 75+</span>
   <span><i class="lg docb"></i>Ocorrência aberta</span>
  </div>
  <div id="unitPanel"></div>
 </section>
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
   <div class="kpi"><div class="l">Ocorrências abertas</div><div class="v">${r.ocorrencias.filter(o => !o.resolvida).length}</div></div>`;
  allOccurrences = r.ocorrencias;
  $('ocN').textContent = `${r.ocorrencias.length} ${r.ocorrencias.length === 1 ? 'registro' : 'registros'}`;
  $('monthN').textContent = `${r.meses.length} meses`;
  renderOccurrences();
  renderProps(r.propostas);
  lastMapa = r.mapa;
  renderBlocks(r.mapa);
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
    ? items.map(o => `<article class="oc ${o.resolvida ? 'done' : ''}"><div class="oc-top">
       <span class="oc-cat">${esc(o.categoria || 'Outro')}</span>
       <div class="oc-right"><time class="oc-date">${esc(o.criado)}</time>
        <button class="oc-btn" data-oc="${o.id}" title="${o.resolvida ? 'Reabrir' : 'Marcar como resolvida'}">${o.resolvida ? '↩ reabrir' : '✓ resolver'}</button></div></div>
       <div class="oc-meta">${esc(o.unidade || 'Sem unidade')} · ${esc(o.nome || 'Anônimo')}</div>
       <div class="oc-txt">${esc(o.texto)}</div></article>`).join('')
    : `<div class="empty">${q ? 'Nenhuma ocorrência corresponde à busca.' : 'Tudo em dia — nenhuma ocorrência registrada.'}</div>`;
}

function renderProps(props) {
  $('propN').textContent = `${props.length} ${props.length === 1 ? 'proposta' : 'propostas'}`;
  $('propList').innerHTML = props.length ? props.map(p => {
    const tot = p.favor + p.contra;
    const pf = tot ? p.favor * 100 / tot : 0;
    return `<article class="prop">
     <div class="prop-top"><span class="pstate ${p.aberta ? 'open' : 'closed'}">${p.aberta ? 'Votação aberta' : 'Encerrada'}</span>
      <time class="oc-date">${esc(p.criado)}</time></div>
     <h4 class="ptit">${esc(p.titulo)}</h4>
     ${p.descricao ? `<p class="pdesc">${esc(p.descricao)}</p>` : ''}
     <div class="vbar"><div class="f" style="width:${pf}%"></div><div class="c" style="width:${100 - pf}%"></div></div>
     <div class="vnums"><span class="fv">${p.favor} a favor</span><span>${tot} ${tot === 1 ? 'voto' : 'votos'}</span><span class="ct">${p.contra} contra</span></div>
     <button class="pbtn" data-prop="${p.id}">${p.aberta ? 'Encerrar votação' : 'Reabrir votação'}</button>
    </article>`;
  }).join('') : '<div class="empty">Nenhuma proposta publicada ainda.</div>';
}
const BLOCOS = ['A1', 'A2', 'A3', 'B1', 'B2', 'B3'];
let lastMapa = {}, selUnit = null;
const FLAG_TXT = { a: 'em atraso', mi: 'mudança (entrada)', mo: 'mudança (saída)', i: 'idoso 75+' };

function renderBlocks(mapa) {
  const nLate = Object.values(mapa).filter(s => s.a).length;
  $('lateN').textContent = `${nLate} em atraso`;
  $('blocks').innerHTML = BLOCOS.map(b => {
    let cells = '', nFlag = 0;
    for (let f = 6; f >= 1; f--)
      for (let n = 1; n <= 4; n++) {
        const id = `${b}-${f}${n}`, st = mapa[id] || {};
        if (st.a) nFlag++;
        const dots = [st.mi && 'din', st.mo && 'dout', st.i && 'did']
          .filter(Boolean).map(c => `<i class="${c}"></i>`).join('');
        const tip = [id, ...Object.keys(FLAG_TXT).filter(k => st[k]).map(k => FLAG_TXT[k]),
          st.oc ? `${st.oc} ocorrência(s) aberta(s)` : ''].filter(Boolean).join(' · ');
        cells += `<button class="apt ${st.a ? 'late' : ''} ${selUnit === id ? 'sel' : ''}"
          data-apt="${id}" title="${esc(tip)}">${f}${n}${dots ? `<span class="dots">${dots}</span>` : ''}${st.oc ? `<span class="ocb">${st.oc}</span>` : ''}</button>`;
      }
    return `<div class="block"><div class="bname">${b}</div>
      <div class="bgrid">${cells}</div>
      <div class="b-tot">${nFlag ? nFlag + ' em atraso' : 'em dia'}</div></div>`;
  }).join('');
  if (selUnit) renderUnitPanel();
}

function renderUnitPanel() {
  const st = lastMapa[selUnit] || {};
  const [bloco, num] = selUnit.split('-');
  const ocs = allOccurrences.filter(o => !o.resolvida && o.unidade === selUnit);
  const flag = (k, label, dot) => `<label class="uflag">
    <input type="checkbox" data-flag="${k}" ${st[k] ? 'checked' : ''}>
    <i class="lg ${dot}"></i>${label}</label>`;
  $('unitPanel').innerHTML = `<div class="upanel">
   <div class="up-head"><div><h3>${selUnit}</h3>
    <div class="up-sub">Bloco ${bloco} · ${num[0]}º andar · Apto ${num}</div></div>
    <button class="up-close" data-close title="Fechar">×</button></div>
   <div class="up-flags">
    ${flag('a', 'Em atraso — sem voto', 'late')}
    ${flag('mi', 'Mudança · entrada', 'din')}
    ${flag('mo', 'Mudança · saída', 'dout')}
    ${flag('i', 'Morador 75+', 'did')}
   </div>
   <div class="up-ocs"><div class="up-ocs-t">Ocorrências abertas</div>
    ${ocs.length ? ocs.map(o => `<div class="up-oc"><span class="oc-cat">${esc(o.categoria || 'Outro')}</span> ${esc(o.texto)}</div>`).join('')
     : 'Nenhuma em aberto.'}</div>
  </div>`;
}
resumo().catch(e => toast(e.message, true));
$('ocSearch').addEventListener('input', renderOccurrences);
$('blocks').addEventListener('click', e => {
  const b = e.target.closest('[data-apt]');
  if (!b) return;
  selUnit = b.dataset.apt;
  document.querySelectorAll('.apt.sel').forEach(x => x.classList.remove('sel'));
  b.classList.add('sel');
  renderUnitPanel();
});
$('unitPanel').addEventListener('click', e => {
  if (!e.target.closest('[data-close]')) return;
  selUnit = null;
  $('unitPanel').innerHTML = '';
  document.querySelectorAll('.apt.sel').forEach(x => x.classList.remove('sel'));
});
$('unitPanel').addEventListener('change', async e => {
  const cb = e.target.closest('[data-flag]');
  if (!cb || !selUnit) return;
  const fd = new FormData(); fd.append('flag', cb.dataset.flag);
  try {
    const r = await fetch(`/admin/unidade/${selUnit}/flag`, { method: 'POST', body: fd });
    const j = await r.json();
    if (!r.ok || !j.ok) throw new Error(j.msg || 'Erro ao atualizar.');
    await resumo();
  } catch (err) { cb.checked = !cb.checked; toast(err.message || 'Falha ao atualizar a unidade.', true); }
});
$('ocList').addEventListener('click', async e => {
  const b = e.target.closest('[data-oc]');
  if (!b) return;
  try {
    const r = await fetch(`/admin/ocorrencia/${b.dataset.oc}/resolver`, { method: 'POST' });
    if (!r.ok) throw new Error();
    await resumo();
  } catch { toast('Falha ao atualizar a ocorrência.', true); }
});
$('propForm').addEventListener('submit', async e => {
  e.preventDefault();
  const fd = new FormData();
  fd.append('titulo', $('propTitulo').value.trim());
  fd.append('descricao', $('propDesc').value.trim());
  try {
    const r = await fetch('/admin/proposta', { method: 'POST', body: fd });
    const j = await r.json();
    toast(j.msg || 'Erro ao publicar.', !r.ok || !j.ok);
    if (r.ok && j.ok) { $('propForm').reset(); await resumo(); }
  } catch { toast('Falha de conexão.', true); }
});
$('propList').addEventListener('click', async e => {
  const b = e.target.closest('[data-prop]');
  if (!b) return;
  try {
    const r = await fetch(`/admin/proposta/${b.dataset.prop}/alternar`, { method: 'POST' });
    if (!r.ok) throw new Error();
    await resumo();
  } catch { toast('Falha ao atualizar a proposta.', true); }
});

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
        'SELECT id, criado_em, unidade, nome, categoria, texto, resolvida '
        'FROM ocorrencias ORDER BY id DESC LIMIT 60').fetchall()
    props = propostas_rows(odb())
    return {
        'meses': [{'am': a, 'label': l, 'rec': r, 'desp': d, 'agua': g}
                  for a, l, r, d, g in meses],
        'ocorrencias': [{'id': i, 'criado': c, 'unidade': u, 'nome': n,
                         'categoria': cat, 'texto': t, 'resolvida': bool(r)}
                        for i, c, u, n, cat, t, r in ocs],
        'propostas': [{'id': i, 'criado': c, 'titulo': t, 'descricao': d,
                       'aberta': bool(ab), 'favor': f, 'contra': co}
                      for i, c, t, d, ab, f, co in props],
        'mapa': mapa_unidades(odb())}


def mapa_unidades(conn):
    """Estado das unidades para o desenho predial — só as que têm alguma
    flag ou ocorrência aberta (o resto é 'em dia' por padrão)."""
    oc_ab = {u: n for u, n in conn.execute(
        'SELECT unidade, COUNT(*) FROM ocorrencias '
        'WHERE resolvida = 0 AND unidade IS NOT NULL GROUP BY unidade')}
    mapa = {}
    for u, a, mi, mo, i in conn.execute(
            'SELECT unidade, em_atraso, mud_in, mud_out, idoso75 FROM unidades'):
        oc = oc_ab.get(u, 0)
        if a or mi or mo or i or oc:
            mapa[u] = {'a': bool(a), 'mi': bool(mi), 'mo': bool(mo),
                       'i': bool(i), 'oc': oc}
    return mapa


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

BLOCOS = ['A1', 'A2', 'A3', 'B1', 'B2', 'B3']  # 6 andares × 4 aptos (11-14 … 61-64)
APTOS = {f'{f}{n}' for f in range(1, 7) for n in range(1, 5)}
UFLAGS = {'a': 'em_atraso', 'mi': 'mud_in', 'mo': 'mud_out', 'i': 'idoso75'}


_db_ready = False


def odb():
    """Conexão com o banco de dados. Na 1ª chamada do processo garante o
    schema (migrações + semente das unidades); depois vira conexão pura —
    sem isso, cada leitura abriria uma transação de escrita e travaria o banco."""
    global _db_ready
    conn = extrair.db_conn()
    if _db_ready:
        return conn
    conn.execute("""CREATE TABLE IF NOT EXISTS ocorrencias(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        criado_em TEXT DEFAULT (datetime('now','localtime')),
        unidade TEXT, nome TEXT, categoria TEXT, texto TEXT NOT NULL)""")
    cols = {r[1] for r in conn.execute('PRAGMA table_info(ocorrencias)')}
    if 'resolvida' not in cols:
        conn.execute('ALTER TABLE ocorrencias ADD COLUMN resolvida INTEGER DEFAULT 0')
    conn.execute("""CREATE TABLE IF NOT EXISTS propostas(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        criado_em TEXT DEFAULT (datetime('now','localtime')),
        titulo TEXT NOT NULL, descricao TEXT, aberta INTEGER DEFAULT 1)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS votos(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        proposta_id INTEGER NOT NULL, unidade TEXT NOT NULL,
        voto TEXT NOT NULL,
        criado_em TEXT DEFAULT (datetime('now','localtime')),
        UNIQUE(proposta_id, unidade))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS unidades(
        unidade TEXT PRIMARY KEY, em_atraso INTEGER DEFAULT 0,
        mud_in INTEGER DEFAULT 0, mud_out INTEGER DEFAULT 0,
        idoso75 INTEGER DEFAULT 0)""")
    cols = {r[1] for r in conn.execute('PRAGMA table_info(unidades)')}
    for col in ('mud_in', 'mud_out', 'idoso75'):
        if col not in cols:
            conn.execute(f'ALTER TABLE unidades ADD COLUMN {col} INTEGER DEFAULT 0')
    conn.executemany(
        'INSERT OR IGNORE INTO unidades(unidade) VALUES (?)',
        [(f'{b}-{f}{n}',) for b in BLOCOS
         for f in range(1, 7) for n in range(1, 5)])
    conn.commit()
    _db_ready = True
    return conn


def propostas_rows(conn):
    return conn.execute(
        """SELECT p.id, p.criado_em, p.titulo, p.descricao, p.aberta,
           COALESCE(SUM(CASE WHEN v.voto='favor' THEN 1 END),0),
           COALESCE(SUM(CASE WHEN v.voto='contra' THEN 1 END),0)
           FROM propostas p LEFT JOIN votos v ON v.proposta_id = p.id
           GROUP BY p.id ORDER BY p.aberta DESC, p.id DESC""").fetchall()


@app.route('/ocorrencia', methods=['GET', 'POST'])
@need_login
def ocorrencia():
    """Qualquer papel logado pode registrar; só admin vê a lista."""
    if request.method == 'POST':
        texto = request.form.get('texto', '').strip()
        bloco = request.form.get('bloco', '').upper()
        apto = request.form.get('apto', '')
        unidade = f'{bloco}-{apto}' if bloco in BLOCOS and apto in APTOS else None
        if not texto:
            return redirect('/ocorrencia?erro=' + urllib.parse.quote(
                'Descreva a ocorrência antes de enviar'))
        if bloco in BLOCOS and apto not in APTOS:
            return redirect('/ocorrencia?erro=' + urllib.parse.quote(
                'Selecione também o apartamento (ou deixe o bloco em "área comum")'))
        conn = odb()
        conn.execute(
            'INSERT INTO ocorrencias(unidade, nome, categoria, texto) VALUES (?,?,?,?)',
            (unidade,
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
    blocos = ''.join(f'<option>{b}</option>' for b in BLOCOS)
    aptos = ''.join(f'<option>{a}</option>' for a in sorted(APTOS))
    return render_template_string(
        PAGE, titulo='Ocorrência',
        body=f'<div class="card"><div class="eyebrow">Livro de ocorrências</div>'
             f'<h1>Registrar ocorrência</h1>'
             f'<p class="mut">Vai direto para a administração — outros condôminos não veem.</p>'
             f'{ok}{erro}'
             f'<form method="post">'
             f'<label>Unidade (opcional)</label>'
             f'<div class="ugrid">'
             f'<select name="bloco" id="blocoSel"><option value="">Área comum / outra</option>{blocos}</select>'
             f'<select name="apto" id="aptoSel" disabled><option value="">Apto…</option>{aptos}</select>'
             f'</div>'
             f'<label>Seu nome (opcional)</label>'
             f'<input type="text" name="nome" placeholder="Anônimo se vazio">'
             f'<label>Categoria</label><select name="categoria">{cats}</select>'
             f'<label>Ocorrência</label>'
             f'<textarea name="texto" required '
             f'placeholder="Descreva o que aconteceu, onde e quando"></textarea>'
             f'<button type="submit">Registrar</button></form>'
             f'<script>var b=document.getElementById("blocoSel"),a=document.getElementById("aptoSel");'
             f'b.addEventListener("change",function(){{a.disabled=!b.value;if(!b.value)a.value="";}});</script>'
             f'<div class="links"><a href="/">← Dashboard</a>'
             f'<a href="/propostas">Votações</a>'
             f'<a href="/logout">Sair</a></div></div>')


@app.get('/admin/ocorrencias')
@need_admin
def admin_ocorrencias():
    return redirect('/admin')


@app.post('/admin/ocorrencia/<int:oid>/resolver')
@need_admin
def resolver_ocorrencia(oid):
    conn = odb()
    conn.execute('UPDATE ocorrencias SET resolvida = 1 - resolvida WHERE id = ?', (oid,))
    conn.commit()
    return {'ok': True}


@app.post('/admin/unidade/<uid>/flag')
@need_admin
def flag_unidade(uid):
    flag = request.form.get('flag', '')
    if flag not in UFLAGS:
        return {'ok': False, 'msg': 'Flag inválida.'}, 400
    conn = odb()
    cur = conn.execute(
        f'UPDATE unidades SET {UFLAGS[flag]} = 1 - {UFLAGS[flag]} WHERE unidade = ?',
        (uid.upper(),))
    conn.commit()
    if not cur.rowcount:
        return {'ok': False, 'msg': 'Unidade desconhecida.'}, 404
    return {'ok': True}


# ---------------- propostas & votação ----------------

PROPOSTAS_HTML = """<!DOCTYPE html><html lang="pt-BR"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow"><title>Propostas · Elit's Park</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;600;700&family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
 :root{--bg:#080d19;--panel:rgba(17,26,45,.78);--border:rgba(148,163,184,.13);
  --muted:#91a0b8;--text:#edf3fc;--cyan:#55d5d0;--favor:#34d399;--contra:#fb7185}
 *{margin:0;padding:0;box-sizing:border-box}
 body{min-height:100vh;padding:34px 24px 70px;color:var(--text);font-family:'Inter',sans-serif;
  background:radial-gradient(900px 500px at 8% -8%,rgba(85,213,208,.13),transparent 63%),
   radial-gradient(700px 430px at 100% 5%,rgba(118,169,255,.10),transparent 65%),
   linear-gradient(145deg,#080d19,#0a1020 58%,#080d19)}
 .wrap{max-width:760px;margin:0 auto}
 .topbar{display:flex;justify-content:space-between;align-items:center;gap:20px;margin-bottom:26px}
 .brand{display:flex;align-items:center;gap:14px}
 .mark{width:46px;height:46px;display:grid;place-items:center;border-radius:15px;
  color:#07131a;background:linear-gradient(145deg,#83e5d4,#50c6c6);font-weight:700;
  box-shadow:0 8px 28px rgba(85,213,208,.18)}
 .eyebrow{color:var(--cyan);font-size:10px;letter-spacing:2.5px;text-transform:uppercase;font-weight:700}
 h1{font-family:'Space Grotesk',sans-serif;font-size:25px;letter-spacing:-.5px}
 .links{display:flex;align-items:center;gap:5px;padding:5px;border:1px solid var(--border);
  border-radius:13px;background:rgba(12,20,36,.75)}
 .links a{font-size:12.5px;font-weight:600;color:var(--muted);padding:9px 12px;
  border-radius:9px;text-decoration:none;transition:.18s;white-space:nowrap}
 .links a:hover{color:var(--text);background:rgba(255,255,255,.05)}
 .links a.exit{color:#ff9eaa}
 .intro{margin:28px 0 18px}
 .intro h2{font-family:'Space Grotesk';font-size:clamp(24px,3vw,32px);letter-spacing:-1px}
 .intro p{color:var(--muted);font-size:14px;margin-top:6px}
 .unit-card{display:flex;align-items:center;gap:12px;flex-wrap:wrap;
  background:linear-gradient(155deg,rgba(17,27,46,.91),rgba(12,19,34,.88));
  border:1px solid var(--border);border-radius:16px;padding:14px 16px;margin-bottom:18px}
 .unit-card label{color:var(--muted);font-size:11px;letter-spacing:1.2px;
  text-transform:uppercase;font-weight:700;white-space:nowrap}
 .unit-card input,.unit-card select{flex:1;min-width:100px;padding:10px 12px;border-radius:10px;
  border:1px solid var(--border);background:rgba(4,10,20,.55);color:var(--text);
  font-family:inherit;font-size:14px;font-weight:600;outline:none}
 .unit-card input:focus,.unit-card select:focus{border-color:var(--cyan)}
 .unit-card select{appearance:auto;cursor:pointer}
 .unit-hint{color:#66758b;font-size:11px;white-space:nowrap}
 .warn{display:flex;align-items:center;gap:10px;color:#ffcf9e;font-size:13px;
  background:rgba(251,146,60,.09);border:1px solid rgba(251,146,60,.35);
  border-radius:12px;padding:12px 15px;margin-bottom:18px}
 .prop{background:linear-gradient(155deg,rgba(17,27,46,.91),rgba(12,19,34,.88));
  border:1px solid var(--border);border-radius:18px;padding:19px 20px;margin-bottom:13px;
  box-shadow:0 15px 45px rgba(0,0,0,.13)}
 .prop-top{display:flex;justify-content:space-between;align-items:center;gap:10px;margin-bottom:9px}
 .pstate{font-size:10px;font-weight:700;padding:4px 9px;border-radius:6px;
  letter-spacing:.8px;text-transform:uppercase}
 .pstate.open{color:#8be2c5;background:rgba(85,213,208,.12);border:1px solid rgba(85,213,208,.25)}
 .pstate.closed{color:#a5b2c6;background:rgba(148,163,184,.1);border:1px solid rgba(148,163,184,.18)}
 .pdate{color:#718098;font-size:10.5px}
 .ptit{font-family:'Space Grotesk';font-size:17px;letter-spacing:-.2px;margin-bottom:5px}
 .pdesc{color:var(--muted);font-size:13px;line-height:1.55;white-space:pre-wrap;overflow-wrap:anywhere}
 .vbar{display:flex;height:9px;border-radius:99px;overflow:hidden;
  background:rgba(148,163,184,.12);margin:13px 0 7px}
 .vbar .f{background:var(--favor)} .vbar .c{background:var(--contra)}
 .vbar .f,.vbar .c{transition:width .4s}
 .vnums{display:flex;justify-content:space-between;font-size:11.5px;color:#a5b2c6}
 .vnums .fv{color:var(--favor);font-weight:700}.vnums .ct{color:var(--contra);font-weight:700}
 .vote-row{display:flex;gap:9px;margin-top:13px}
 .vb{flex:1;padding:11px;border-radius:10px;font-weight:700;font-size:13px;cursor:pointer;
  transition:.15s;border:1px solid}
 .vb.favor{color:var(--favor);border-color:rgba(52,211,153,.35);background:rgba(52,211,153,.07)}
 .vb.favor:hover{background:rgba(52,211,153,.16)}
 .vb.contra{color:var(--contra);border-color:rgba(251,113,133,.35);background:rgba(251,113,133,.07)}
 .vb.contra:hover{background:rgba(251,113,133,.16)}
 .vb.mine{outline:2px solid currentColor;outline-offset:1px}
 .voted{font-size:11.5px;color:#a5b2c6;margin-top:9px;text-align:center}
 .voted b{color:var(--cyan)}
 .empty{color:var(--muted);text-align:center;padding:44px 14px;font-size:13.5px}
 #toast{position:fixed;bottom:24px;left:50%;transform:translate(-50%,80px);opacity:0;
  transition:.25s;background:#101a2b;border:1px solid rgba(85,213,208,.4);border-radius:12px;
  padding:12px 18px;font-size:13px;box-shadow:0 14px 40px rgba(0,0,0,.55);z-index:99;max-width:90vw}
 #toast.show{transform:translate(-50%,0);opacity:1}
 #toast.bad{border-color:rgba(251,113,133,.5)}
 @media(max-width:650px){
  body{padding:15px 13px 48px}.topbar{align-items:flex-start;flex-direction:column;gap:13px}
  .links{width:100%;overflow-x:auto}.links a{flex:1;text-align:center;padding:8px 7px;font-size:11px}
  .mark{width:40px;height:40px}.unit-card{flex-direction:column;align-items:stretch}
  .unit-hint{text-align:center}.vote-row{flex-direction:column}
 }
</style><link rel="stylesheet" href="/theme.css"></head><body>
<div class="wrap">
 <div class="topbar">
  <div class="brand"><div class="mark" aria-hidden="true">EP</div>
   <div><div class="eyebrow">Condomínio Elit's Park</div><h1>Propostas & votações</h1></div>
  </div>
  <div class="links">
   <a href="/">Painel</a><a href="/historico.html">Histórico</a>
   <a href="/ocorrencia">Ocorrência</a><a class="exit" href="/logout">Sair</a>
  </div>
 </div>
 <section class="intro">
  <h2>Decida junto.</h2>
  <p>Propostas da administração abertas à votação — um voto por unidade, você pode mudar enquanto a votação estiver aberta.</p>
 </section>
 <div class="unit-card">
  <label>Sua unidade</label>
  <select id="uBloco"><option value="">Bloco…</option></select>
  <select id="uApto"><option value="">Apto…</option></select>
  <span class="unit-hint">Necessária para votar · fica salva neste aparelho</span>
 </div>
 <div id="avisoAtraso"></div>
 <div id="lista"></div>
</div>
<div id="toast"></div>
<script>
const $ = id => document.getElementById(id);
const esc = s => String(s ?? '').replace(/[&<>"']/g,
  c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
let props = [], emAtraso = false;

function toast(msg, bad) {
  const t = $('toast'); t.textContent = msg;
  t.className = 'show' + (bad ? ' bad' : '');
  clearTimeout(t._h); t._h = setTimeout(() => t.className = '', 4200);
}

const BLOCOS_P = ['A1', 'A2', 'A3', 'B1', 'B2', 'B3'];
$('uBloco').innerHTML += BLOCOS_P.map(b => `<option>${b}</option>`).join('');
let _ao = '';
for (let f = 1; f <= 6; f++) for (let n = 1; n <= 4; n++) _ao += `<option>${f}${n}</option>`;
$('uApto').innerHTML += _ao;

function unidade() {
  const b = $('uBloco').value, a = $('uApto').value;
  return b && a ? `${b}-${a}` : '';
}

async function carregar() {
  const u = unidade();
  const r = await fetch('/api/propostas' + (u ? '?unidade=' + encodeURIComponent(u) : ''));
  if (!r.ok) throw new Error('Não foi possível carregar as propostas.');
  const j = await r.json();
  props = j.propostas;
  emAtraso = j.unidade_em_atraso;
  $('avisoAtraso').innerHTML = emAtraso
    ? '<div class="warn">⚠ <span>Unidade em atraso — a votação fica suspensa até a regularização com a administração.</span></div>'
    : '';
  render();
}

function render() {
  $('lista').innerHTML = props.length ? props.map(p => {
    const tot = p.favor + p.contra;
    const pf = tot ? p.favor * 100 / tot : 0;
    const btns = !p.aberta ? '' : emAtraso
      ? '<div class="voted">Votação suspensa para esta unidade.</div>'
      : `<div class="vote-row">
      <button class="vb favor ${p.meu_voto === 'favor' ? 'mine' : ''}" data-v="favor" data-p="${p.id}">👍 A favor</button>
      <button class="vb contra ${p.meu_voto === 'contra' ? 'mine' : ''}" data-v="contra" data-p="${p.id}">👎 Contra</button>
     </div>
     ${p.meu_voto ? `<div class="voted">Seu voto atual: <b>${p.meu_voto === 'favor' ? 'a favor' : 'contra'}</b> — vote de novo para mudar</div>` : ''}`;
    return `<article class="prop">
     <div class="prop-top"><span class="pstate ${p.aberta ? 'open' : 'closed'}">${p.aberta ? 'Votação aberta' : 'Encerrada'}</span>
      <time class="pdate">${esc(p.criado)}</time></div>
     <h3 class="ptit">${esc(p.titulo)}</h3>
     ${p.descricao ? `<p class="pdesc">${esc(p.descricao)}</p>` : ''}
     <div class="vbar"><div class="f" style="width:${pf}%"></div><div class="c" style="width:${100 - pf}%"></div></div>
     <div class="vnums"><span class="fv">${p.favor} a favor</span><span>${tot} ${tot === 1 ? 'voto' : 'votos'}</span><span class="ct">${p.contra} contra</span></div>
     ${btns}
    </article>`;
  }).join('') : '<div class="empty">Nenhuma proposta publicada ainda.</div>';
}

$('lista').addEventListener('click', async e => {
  const b = e.target.closest('[data-v]');
  if (!b) return;
  if (!unidade()) { toast('Selecione bloco e apartamento para votar.', true); $('uBloco').focus(); return; }
  const fd = new FormData();
  fd.append('unidade', unidade()); fd.append('voto', b.dataset.v);
  try {
    const r = await fetch(`/proposta/${b.dataset.p}/voto`, { method: 'POST', body: fd });
    const j = await r.json();
    toast(j.msg || 'Erro ao votar.', !r.ok || !j.ok);
    if (r.ok && j.ok) await carregar();
  } catch { toast('Falha de conexão.', true); }
});

const _sv = (localStorage.getItem('prop_unidade') || '').match(/^([A-B]\\d)-(\\d\\d)$/);
if (_sv) { $('uBloco').value = _sv[1]; $('uApto').value = _sv[2]; }
['uBloco', 'uApto'].forEach(id => $(id).addEventListener('change', () => {
  localStorage.setItem('prop_unidade', unidade());
  carregar().catch(() => {});
}));
carregar().catch(e => toast(e.message, true));
</script></body></html>"""


@app.get('/propostas')
@need_login
def propostas_page():
    return PROPOSTAS_HTML


@app.get('/api/propostas')
@need_login
def api_propostas():
    conn = odb()
    unidade = request.args.get('unidade', '').strip().upper()
    mine = {}
    em_atraso = False
    if unidade:
        mine = {pid: v for pid, v in conn.execute(
            'SELECT proposta_id, voto FROM votos WHERE unidade = ?', (unidade,))}
        u = conn.execute(
            'SELECT em_atraso FROM unidades WHERE unidade = ?', (unidade,)).fetchone()
        em_atraso = bool(u and u[0])
    return {'unidade_em_atraso': em_atraso, 'propostas': [
        {'id': i, 'criado': c, 'titulo': t, 'descricao': d, 'aberta': bool(ab),
         'favor': f, 'contra': co, 'meu_voto': mine.get(i)}
        for i, c, t, d, ab, f, co in propostas_rows(conn)]}


@app.post('/proposta/<int:pid>/voto')
@need_login
def votar(pid):
    unidade = request.form.get('unidade', '').strip().upper()
    voto = request.form.get('voto', '')
    if not unidade or voto not in ('favor', 'contra'):
        return {'ok': False, 'msg': 'Informe sua unidade e escolha uma opção.'}, 400
    conn = odb()
    u = conn.execute(
        'SELECT em_atraso FROM unidades WHERE unidade = ?', (unidade,)).fetchone()
    if not u:
        return {'ok': False,
                'msg': 'Unidade não encontrada — formato BLOCO-NÚMERO (ex.: A3-11).'}, 400
    if u[0]:
        return {'ok': False,
                'msg': 'Unidade em atraso — regularize com a administração para votar.'}, 403
    p = conn.execute('SELECT aberta FROM propostas WHERE id = ?', (pid,)).fetchone()
    if not p:
        return {'ok': False, 'msg': 'Proposta não encontrada.'}, 404
    if not p[0]:
        return {'ok': False, 'msg': 'Votação encerrada.'}, 400
    conn.execute(
        """INSERT INTO votos(proposta_id, unidade, voto) VALUES (?,?,?)
           ON CONFLICT(proposta_id, unidade) DO UPDATE SET voto = excluded.voto""",
        (pid, unidade, voto))
    conn.commit()
    return {'ok': True, 'msg': 'Voto registrado — obrigado!'}


@app.post('/admin/proposta')
@need_admin
def nova_proposta():
    titulo = request.form.get('titulo', '').strip()
    if not titulo:
        return {'ok': False, 'msg': 'Informe o título da proposta.'}, 400
    conn = odb()
    conn.execute('INSERT INTO propostas(titulo, descricao) VALUES (?,?)',
                 (titulo, request.form.get('descricao', '').strip() or None))
    conn.commit()
    return {'ok': True, 'msg': 'Proposta publicada para votação'}


@app.post('/admin/proposta/<int:pid>/alternar')
@need_admin
def alternar_proposta(pid):
    conn = odb()
    conn.execute('UPDATE propostas SET aberta = 1 - aberta WHERE id = ?', (pid,))
    conn.commit()
    return {'ok': True}


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
