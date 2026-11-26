"""
Servidor do dashboard — dois níveis de acesso:

  morador: vê index/histórico e simula o próprio boleto
  admin:   idem + sobe o PDF do balancete (vira base para todos)

Variáveis de ambiente obrigatórias:
  ADMIN_PASSWORD, MORADOR_PASSWORD   (SECRET_KEY opcional — sessões)

Dev:   python3 app.py
Prod:  gunicorn -b 0.0.0.0:8000 -w 2 app:app
"""
import hashlib
import hmac
import json
import os
import secrets
import smtplib
import urllib.parse
import urllib.request
from email.message import EmailMessage
from functools import wraps
from pathlib import Path

from flask import (Flask, redirect, render_template, request,
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
if not ADMIN_PW:
    raise SystemExit('Defina ADMIN_PASSWORD no ambiente. '
                     '(MORADOR_PASSWORD é opcional — acesso genérico sem unidade.)')




def role():
    return session.get('role')


@app.before_request
def _force_troca_senha():
    """Morador com código temporário só acessa a troca de senha."""
    if session.get('trocar') and request.endpoint not in (
            'trocar_senha', 'logout', 'theme_css', 'static_files', 'static'):
        return redirect('/trocar-senha')


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
            return render_template('erro403.html'), 403
        return f(*a, **kw)
    return w


@app.get('/login')
def login():
    if role():
        return redirect('/')
    msgs = {'e': 'Senha ou código incorreto — tente novamente.',
            'unidade': 'Selecione bloco e apartamento.',
            'semcodigo': 'Esta unidade ainda não tem código — peça à administração.'}
    e = request.args.get('e', '')
    return render_template('login.html',
                           erro=msgs.get(e, msgs['e']) if e else None,
                           blocos=BLOCOS, aptos=sorted(APTOS))


@app.post('/login')
def do_login():
    if request.form.get('modo') == 'morador':
        bloco = request.form.get('bloco', '').upper()
        apto = request.form.get('apto', '')
        uid = f'{bloco}-{apto}'
        if bloco not in BLOCOS or apto not in APTOS:
            return redirect('/login?e=unidade')
        row = odb().execute('SELECT codigo, senha_temp FROM unidades WHERE unidade = ?',
                            (uid,)).fetchone()
        if not row or not row[0]:
            return redirect('/login?e=semcodigo')
        codigo = request.form.get('codigo', '').strip()
        if not hmac.compare_digest(row[0], hashlib.sha256(codigo.encode()).hexdigest()):
            return redirect('/login?e=e')
        session['role'] = 'morador'
        session['unidade'] = uid
        if row[1]:
            session['trocar'] = 1
            resp = redirect('/trocar-senha')
            resp.set_cookie('cond_app', '1')
            resp.set_cookie('cond_role', 'morador')
            return resp
    else:
        pw = request.form.get('senha', '')
        r = 'admin' if hmac.compare_digest(pw, ADMIN_PW) else \
            'morador' if MORADOR_PW and hmac.compare_digest(pw, MORADOR_PW) else None
        if not r:
            return redirect('/login?e=e')
        session['role'] = r
    resp = redirect('/')
    # cookies-hint: senha.js não bloqueia quem já logou; nav mostra link Admin
    resp.set_cookie('cond_app', '1')
    resp.set_cookie('cond_role', session['role'])
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
    return render_template('admin.html', heading='Central do condomínio',
                           eyebrow="Elit's Park · Administração", active='admin')


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
        'advertencias': [{'id': i, 'criado': c, 'unidade': u, 'texto': t}
                         for i, c, u, t in odb().execute(
            'SELECT id, criado_em, unidade, texto FROM advertencias '
            'ORDER BY id DESC LIMIT 200').fetchall()],
        'codigos': [u for u, in odb().execute(
            'SELECT unidade FROM unidades WHERE codigo IS NOT NULL')],
        'emails': {u: e for u, e in odb().execute(
            'SELECT unidade, email FROM unidades WHERE email IS NOT NULL')},
        'telefones': {u: fmt_fone(t) for u, t in odb().execute(
            'SELECT unidade, telefone FROM unidades WHERE telefone IS NOT NULL')},
        'evo': evo_ok(),
        'mapa': mapa_unidades(odb())}


def mapa_unidades(conn):
    """Estado das unidades para o desenho predial — só as que têm alguma
    flag ou ocorrência aberta (o resto é 'em dia' por padrão)."""
    oc_ab = {u: n for u, n in conn.execute(
        'SELECT unidade, COUNT(*) FROM ocorrencias '
        'WHERE resolvida = 0 AND unidade IS NOT NULL GROUP BY unidade')}
    adv_ab = {u: n for u, n in conn.execute(
        'SELECT unidade, COUNT(*) FROM advertencias GROUP BY unidade')}
    mapa = {}
    for u, a, mi, mo, i in conn.execute(
            'SELECT unidade, em_atraso, mud_in, mud_out, idoso75 FROM unidades'):
        oc = oc_ab.get(u, 0)
        if a or mi or mo or i or oc or u in adv_ab:
            mapa[u] = {'a': bool(a), 'mi': bool(mi), 'mo': bool(mo),
                       'i': bool(i), 'oc': oc, 'adv': adv_ab.get(u, 0)}
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

SMTP = {k: os.environ.get(f'SMTP_{k}', '') for k in ('HOST', 'PORT', 'USER', 'PASS', 'FROM')}
PUBLIC_URL = os.environ.get('PUBLIC_URL', 'http://localhost:8080')
EVO = {k: os.environ.get(f'EVO_{k}', '') for k in ('URL', 'KEY', 'INSTANCE')}


def smtp_ok():
    return bool(SMTP['HOST'] and SMTP['FROM'] and (not SMTP['USER'] or SMTP['PASS']))


def norm_fone(s):
    """Telefone → dígitos internacionais (55+DDD+número). Vazio → None."""
    d = ''.join(c for c in (s or '') if c.isdigit())
    if not d:
        return None
    if len(d) in (10, 11):          # DDD + número local
        d = '55' + d
    if not (d.startswith('55') and len(d) in (12, 13)):
        raise ValueError('Telefone deve ser DDD + número (ex.: 19 99999-8888)')
    return d


def fmt_fone(d):
    """5519999998888 → '+55 19 99999-8888' para exibição."""
    if not d:
        return ''
    if len(d) == 13:
        return f'+{d[:2]} {d[2:4]} {d[4:9]}-{d[9:]}'
    if len(d) == 12:
        return f'+{d[:2]} {d[2:4]} {d[4:8]}-{d[8:]}'
    return d


def norm_email(s):
    s = (s or '').strip().lower()
    if s and ('@' not in s or len(s) > 120):
        raise ValueError('E-mail inválido.')
    return s or None


def enviar_codigo(unidade, email, codigo):
    """Envia o código temporário da unidade por e-mail (smtplib)."""
    msg = EmailMessage()
    msg['Subject'] = f"Condomínio Elit's Park — acesso da unidade {unidade}"
    msg['From'] = SMTP['FROM']
    msg['To'] = email
    msg.set_content(
        f"Olá, morador da unidade {unidade}!\n\n"
        f"Seu código de acesso ao portal do condomínio:\n\n"
        f"    {codigo}\n\n"
        f"Entre em {PUBLIC_URL} , aba \"Sou morador\": selecione bloco e "
        f"apartamento e informe o código.\n"
        f"No primeiro acesso você define sua senha pessoal — guarde-a, "
        f"o código expira após a troca.\n\n"
        f"— Administração do Condomínio Elit's Park\n")
    with smtplib.SMTP(SMTP['HOST'], int(SMTP['PORT'] or 587), timeout=10) as s:
        s.ehlo()
        s.starttls()
        if SMTP['USER']:
            s.login(SMTP['USER'], SMTP['PASS'])
        s.send_message(msg)


def evo_ok():
    """Evolution API configurada (self-hosted) — URL + apikey + instância."""
    return all(EVO.values())


def enviar_whatsapp(number, texto):
    """POST /message/sendText/{instance} — number = dígitos (55…) ou JID."""
    payload = json.dumps({'number': number, 'text': texto}).encode()
    req = urllib.request.Request(
        f"{EVO['URL'].rstrip('/')}/message/sendText/{EVO['INSTANCE']}",
        data=payload,
        headers={'Content-Type': 'application/json', 'apikey': EVO['KEY']})
    urllib.request.urlopen(req, timeout=15).read()


def enviar_codigo_whatsapp(unidade, fone, codigo):
    """Envia o código temporário por WhatsApp via Evolution API.
    `fone` já vem normalizado (55+DDD+número) — formato aceito pelo endpoint."""
    enviar_whatsapp(
        fone,
        f"Condomínio Elit's Park — unidade {unidade}\n\n"
        f"Seu código de acesso ao portal: *{codigo}*\n\n"
        f"Entre em {PUBLIC_URL} (aba \"Sou morador\"): selecione bloco "
        f"e apartamento e informe o código. No primeiro acesso você "
        f"define sua senha pessoal — o código expira após a troca.")


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
        idoso75 INTEGER DEFAULT 0, codigo TEXT, email TEXT,
        telefone TEXT, senha_temp INTEGER DEFAULT 1)""")
    cols = {r[1] for r in conn.execute('PRAGMA table_info(unidades)')}
    for col in ('mud_in', 'mud_out', 'idoso75', 'senha_temp'):
        if col not in cols:
            conn.execute(f'ALTER TABLE unidades ADD COLUMN {col} INTEGER DEFAULT 1')
    if 'codigo' not in cols:
        conn.execute('ALTER TABLE unidades ADD COLUMN codigo TEXT')
    if 'email' not in cols:
        conn.execute('ALTER TABLE unidades ADD COLUMN email TEXT')
    if 'telefone' not in cols:
        conn.execute('ALTER TABLE unidades ADD COLUMN telefone TEXT')
    conn.executemany(
        'INSERT OR IGNORE INTO unidades(unidade) VALUES (?)',
        [(f'{b}-{f}{n}',) for b in BLOCOS
         for f in range(1, 7) for n in range(1, 5)])
    conn.execute("""CREATE TABLE IF NOT EXISTS advertencias(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        criado_em TEXT DEFAULT (datetime('now','localtime')),
        unidade TEXT NOT NULL, texto TEXT NOT NULL)""")
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

    ub = (session.get('unidade') or '').split('-')
    return render_template(
        'ocorrencia.html', ok=bool(request.args.get('ok')),
        erro=request.args.get('erro'), categorias=CATEGORIAS,
        blocos=BLOCOS, aptos=sorted(APTOS),
        pre_bloco=ub[0], pre_apto=ub[1] if len(ub) == 2 else '',
        heading='Registrar ocorrência', active='oc')


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


@app.post('/admin/unidade/<uid>/advertencia')
@need_admin
def nova_advertencia(uid):
    texto = request.form.get('texto', '').strip()
    if not texto:
        return {'ok': False, 'msg': 'Descreva a advertência.'}, 400
    conn = odb()
    conn.execute('INSERT INTO advertencias(unidade, texto) VALUES (?,?)',
                 (uid.upper(), texto))
    conn.commit()
    return {'ok': True, 'msg': f'Advertência registrada para {uid.upper()}'}


@app.post('/admin/advertencia/<int:aid>/remover')
@need_admin
def remover_advertencia(aid):
    conn = odb()
    conn.execute('DELETE FROM advertencias WHERE id = ?', (aid,))
    conn.commit()
    return {'ok': True}


@app.route('/trocar-senha', methods=['GET', 'POST'])
def trocar_senha():
    """Aceite do código: o morador define a senha própria (obrigatório
    enquanto session['trocar'] estiver setado — ver before_request)."""
    if not session.get('unidade') or not session.get('trocar'):
        return redirect('/')
    if request.method == 'POST':
        s1 = request.form.get('senha', '')
        s2 = request.form.get('senha2', '')
        if len(s1) < 6:
            return redirect('/trocar-senha?erro=' + urllib.parse.quote(
                'Use pelo menos 6 caracteres.'))
        if s1 != s2:
            return redirect('/trocar-senha?erro=' + urllib.parse.quote(
                'As senhas não coincidem.'))
        conn = odb()
        conn.execute('UPDATE unidades SET codigo = ?, senha_temp = 0 WHERE unidade = ?',
                     (hashlib.sha256(s1.encode()).hexdigest(), session['unidade']))
        conn.commit()
        session.pop('trocar')
        return redirect('/')
    return render_template('trocar.html',
                           erro=request.args.get('erro'),
                           unidade=session['unidade'])


@app.post('/admin/codigos/gerar')
@need_admin
def gerar_codigos():
    """Emite código para toda unidade sem código; devolve a lista uma
    vez (para distribuição) — no banco ficam só os hashes."""
    conn = odb()
    novos = {}
    for (u,) in conn.execute(
            'SELECT unidade FROM unidades WHERE codigo IS NULL ORDER BY unidade'):
        c = f'{secrets.randbelow(9000) + 1000}'
        conn.execute('UPDATE unidades SET codigo = ?, senha_temp = 1 WHERE unidade = ?',
                     (hashlib.sha256(c.encode()).hexdigest(), u))
        novos[u] = c
    conn.commit()
    return {'ok': True, 'novos': novos, 'total': len(novos)}


@app.post('/admin/unidade/<uid>/codigo')
@need_admin
def gerar_codigo(uid):
    """Gera código de acesso da unidade (4 dígitos); devolve uma vez —
    no banco fica só o hash. Trocar o código invalida o anterior."""
    uid = uid.upper()
    conn = odb()
    if not conn.execute('SELECT 1 FROM unidades WHERE unidade = ?',
                        (uid,)).fetchone():
        return {'ok': False, 'msg': 'Unidade desconhecida.'}, 404
    codigo = f'{secrets.randbelow(9000) + 1000}'
    conn.execute('UPDATE unidades SET codigo = ?, senha_temp = 1 WHERE unidade = ?',
                 (hashlib.sha256(codigo.encode()).hexdigest(), uid))
    conn.commit()
    return {'ok': True, 'codigo': codigo}


@app.post('/admin/unidade/<uid>/email')
@need_admin
def salvar_email(uid):
    """Contato da unidade (admin): e-mail e/ou telefone. Campos ausentes
    no form não são alterados; campo presente vazio limpa o valor."""
    try:
        email = norm_email(request.form['email']) if 'email' in request.form else ...
        fone = norm_fone(request.form['telefone']) if 'telefone' in request.form else ...
    except ValueError as e:
        return {'ok': False, 'msg': str(e)}, 400
    conn = odb()
    if not conn.execute('SELECT 1 FROM unidades WHERE unidade = ?',
                        (uid.upper(),)).fetchone():
        return {'ok': False, 'msg': 'Unidade desconhecida.'}, 404
    if email is not ...:
        conn.execute('UPDATE unidades SET email = ? WHERE unidade = ?',
                     (email, uid.upper()))
    if fone is not ...:
        conn.execute('UPDATE unidades SET telefone = ? WHERE unidade = ?',
                     (fone, uid.upper()))
    conn.commit()
    return {'ok': True}


@app.post('/admin/unidade/<uid>/email/enviar')
@need_admin
def enviar_codigo_email(uid):
    """Gera código temporário e envia por e-mail — também serve como
    reset de acesso (invalida a senha atual → aceite de novo)."""
    uid = uid.upper()
    conn = odb()
    row = conn.execute('SELECT email FROM unidades WHERE unidade = ?',
                       (uid,)).fetchone()
    if not row or not row[0]:
        return {'ok': False, 'msg': 'Cadastre o e-mail da unidade primeiro.'}, 400
    if not smtp_ok():
        return {'ok': False,
                'msg': 'SMTP não configurado (SMTP_HOST/FROM/USER/PASS no env).'}, 400
    codigo = f'{secrets.randbelow(9000) + 1000}'
    try:
        enviar_codigo(uid, row[0], codigo)
    except Exception as e:
        return {'ok': False, 'msg': f'Falha ao enviar: {e}'}, 502
    conn.execute('UPDATE unidades SET codigo = ?, senha_temp = 1 WHERE unidade = ?',
                 (hashlib.sha256(codigo.encode()).hexdigest(), uid))
    conn.commit()
    return {'ok': True, 'msg': f'Código enviado para {row[0]}'}


@app.post('/admin/unidade/<uid>/whatsapp/enviar')
@need_admin
def enviar_codigo_whatsapp_route(uid):
    """Mesmo fluxo do envio por e-mail, via WhatsApp (Evolution API)."""
    uid = uid.upper()
    conn = odb()
    row = conn.execute('SELECT telefone FROM unidades WHERE unidade = ?',
                       (uid,)).fetchone()
    if not row or not row[0]:
        return {'ok': False, 'msg': 'Cadastre o telefone da unidade primeiro.'}, 400
    if not evo_ok():
        return {'ok': False,
                'msg': 'Evolution API não configurada (EVO_URL/KEY/INSTANCE no env).'}, 400
    codigo = f'{secrets.randbelow(9000) + 1000}'
    try:
        enviar_codigo_whatsapp(uid, row[0], codigo)
    except Exception as e:
        return {'ok': False, 'msg': f'Falha ao enviar: {e}'}, 502
    conn.execute('UPDATE unidades SET codigo = ?, senha_temp = 1 WHERE unidade = ?',
                 (hashlib.sha256(codigo.encode()).hexdigest(), uid))
    conn.commit()
    return {'ok': True, 'msg': f'Código enviado por WhatsApp para {fmt_fone(row[0])}'}


# ---------------- WhatsApp: mensagens recebidas (webhook Evolution) ----------------

WA_HELP = ("🤖 *Portaria virtual — Condomínio Elit's Park*\n\n"
           "Comandos:\n"
           "• *OCORRENCIA* <relato> — registra no livro de ocorrências\n"
           "• *VOTACAO* — lista as votações abertas\n"
           "• *VOTAR <n> FAVOR* ou *VOTAR <n> CONTRA*\n"
           "• *AJUDA* — esta mensagem")


def _wa_reply(number, texto):
    """Resposta best-effort — falha de envio nunca derruba o webhook."""
    try:
        enviar_whatsapp(number, texto)
    except Exception:
        pass


def _wa_comando(conn, cmd, resto, uid, nome):
    """Executa o comando do morador e devolve a resposta (ou None)."""
    if cmd in ('OCORRENCIA', 'OCORRÊNCIA', 'RECLAMACAO', 'RECLAMAÇÃO'):
        if not uid:
            return ('⚠️ Seu número não está vinculado a uma unidade — '
                    'peça à administração para cadastrar seu telefone no perfil.')
        if not resto:
            return ('Envie *OCORRENCIA* seguido do relato.\n'
                    'Ex.: OCORRENCIA vazamento na garagem G2')
        conn.execute('INSERT INTO ocorrencias(unidade, nome, categoria, texto) '
                     'VALUES (?,?,?,?)', (uid, nome or None, 'whatsapp', resto[:1000]))
        conn.commit()
        return (f'✅ Ocorrência registrada no livro ({uid}) — '
                f'a administração acompanha pelo painel.')
    if cmd in ('VOTACAO', 'VOTAÇÃO', 'VOTACOES', 'VOTAÇÕES', 'PAUTA', 'PROPOSTAS'):
        rows = conn.execute('SELECT id, titulo FROM propostas WHERE aberta = 1 '
                            'ORDER BY id').fetchall()
        if not rows:
            return 'Nenhuma votação aberta no momento.'
        linhas = '\n'.join(f'*{i}* — {t}' for i, t in rows)
        return (f'🗳️ *Votações abertas:*\n{linhas}\n\n'
                f'Responda *VOTAR <n> FAVOR* ou *VOTAR <n> CONTRA*.')
    if cmd == 'VOTAR':
        if not uid:
            return ('⚠️ Seu número não está vinculado a uma unidade — '
                    'peça à administração para cadastrar seu telefone no perfil.')
        m = resto.split()
        pid = int(m[0]) if m and m[0].isdigit() else 0
        op = m[1].upper() if len(m) > 1 else ''
        voto = 'favor' if op.startswith('F') else 'contra' if op.startswith('C') else ''
        if not pid or not voto:
            return ('Formato: *VOTAR <n> FAVOR* ou *VOTAR <n> CONTRA*. '
                    'Veja os números com *VOTACAO*.')
        u = conn.execute('SELECT em_atraso FROM unidades WHERE unidade = ?',
                         (uid,)).fetchone()
        if u and u[0]:
            return '🚫 Unidade em atraso — regularize com a administração para votar.'
        p = conn.execute('SELECT titulo, aberta FROM propostas WHERE id = ?',
                         (pid,)).fetchone()
        if not p:
            return 'Proposta não encontrada — veja as abertas com *VOTACAO*.'
        if not p[1]:
            return f'A votação *{p[0]}* já está encerrada.'
        conn.execute(
            """INSERT INTO votos(proposta_id, unidade, voto) VALUES (?,?,?)
               ON CONFLICT(proposta_id, unidade) DO UPDATE SET voto = excluded.voto""",
            (pid, uid, voto))
        conn.commit()
        f, c = conn.execute(
            "SELECT SUM(voto='favor'), SUM(voto='contra') FROM votos "
            'WHERE proposta_id = ?', (pid,)).fetchone()
        return (f'✅ Voto *{"a favor" if voto == "favor" else "contra"}* '
                f'de {uid} registrado na proposta *{p[0]}*.\n'
                f'Placar: {f or 0}× favor · {c or 0}× contra.')
    if cmd in ('AJUDA', 'MENU', 'OI', 'OLA', 'OLÁ', 'BOM', 'BOA',
               'INICIO', 'INÍCIO', 'START'):
        return WA_HELP
    return 'Comando não reconhecido. Responda *AJUDA* para ver os comandos.'


@app.post('/webhook/whatsapp')
def webhook_whatsapp():
    """Endpoint do webhook da Evolution API (evento MESSAGES_UPSERT).
    Auth: header apikey = EVO_KEY (ou ?key=). Mensagens de texto viram
    comandos da portaria virtual — ver _wa_comando."""
    if not evo_ok():
        return {'ok': False}, 404
    if (request.headers.get('apikey') != EVO['KEY']
            and request.args.get('key') != EVO['KEY']):
        return {'ok': False}, 401
    body = request.get_json(silent=True) or {}
    if (body.get('event') or '').lower() != 'messages.upsert':
        return {'ok': True, 'skipped': body.get('event') or 'no-event'}
    data = body.get('data') or {}
    key = data.get('key') or {}
    jid = key.get('remoteJid') or ''
    if (key.get('fromMe') or jid.endswith('@g.us')
            or jid == 'status@broadcast'):
        return {'ok': True, 'skipped': 'self/group/broadcast'}
    msg = data.get('message') or {}
    texto = (msg.get('conversation')
             or (msg.get('extendedTextMessage') or {}).get('text')
             or '').strip()
    if not texto:
        return {'ok': True, 'skipped': 'non-text'}
    digits = ''.join(c for c in jid.split('@')[0] if c.isdigit())
    if jid.endswith('@lid'):  # JID privado — telefone real vem em senderPn
        alt = key.get('senderPn') or key.get('remoteJidAlt') or ''
        digits = ''.join(c for c in alt if c.isdigit()) or digits
    conn = odb()
    row = conn.execute('SELECT unidade FROM unidades WHERE telefone = ?',
                       (digits,)).fetchone() if digits else None
    uid = row[0] if row else None
    nome = (data.get('pushName') or '').strip()
    parts = texto.split(None, 1)
    cmd = parts[0].upper().strip('.,!;:*')
    resto = parts[1].strip() if len(parts) > 1 else ''
    reply_to = digits or jid
    try:
        resposta = _wa_comando(conn, cmd, resto, uid, nome)
    except Exception:
        resposta = None
    if resposta:
        _wa_reply(reply_to, resposta)
    return {'ok': True}


@app.post('/admin/codigos/email')
@need_admin
def enviar_codigos_email():
    """Envia código temporário por e-mail para toda unidade que tem
    e-mail cadastrado e ainda não definiu senha própria."""
    if not smtp_ok():
        return {'ok': False,
                'msg': 'SMTP não configurado (SMTP_HOST/FROM/USER/PASS no env).'}, 400
    conn = odb()
    rows = conn.execute(
        'SELECT unidade, email FROM unidades WHERE email IS NOT NULL '
        'AND senha_temp = 1 ORDER BY unidade').fetchall()
    sent = fail = 0
    for u, e in rows:
        codigo = f'{secrets.randbelow(9000) + 1000}'
        try:
            enviar_codigo(u, e, codigo)
            conn.execute(
                'UPDATE unidades SET codigo = ?, senha_temp = 1 WHERE unidade = ?',
                (hashlib.sha256(codigo.encode()).hexdigest(), u))
            conn.commit()
            sent += 1
        except Exception:
            fail += 1
    return {'ok': True,
            'msg': f'{sent} código(s) enviado(s)' + (f', {fail} falha(s)' if fail else '')}


# ---------------- propostas & votação ----------------




@app.get('/propostas')
@need_login
def propostas_page():
    return render_template('propostas.html', heading='Propostas & votações',
                           active='vot')


@app.get('/api/propostas')
@need_login
def api_propostas():
    conn = odb()
    unidade = session.get('unidade') or request.args.get('unidade', '').strip().upper()
    mine = {}
    em_atraso = False
    if unidade:
        mine = {pid: v for pid, v in conn.execute(
            'SELECT proposta_id, voto FROM votos WHERE unidade = ?', (unidade,))}
        u = conn.execute(
            'SELECT em_atraso FROM unidades WHERE unidade = ?', (unidade,)).fetchone()
        em_atraso = bool(u and u[0])
    return {'unidade_em_atraso': em_atraso,
            'sessao_unidade': session.get('unidade'), 'propostas': [
        {'id': i, 'criado': c, 'titulo': t, 'descricao': d, 'aberta': bool(ab),
         'favor': f, 'contra': co, 'meu_voto': mine.get(i)}
        for i, c, t, d, ab, f, co in propostas_rows(conn)]}


@app.post('/proposta/<int:pid>/voto')
@need_login
def votar(pid):
    unidade = session.get('unidade') or request.form.get('unidade', '').strip().upper()
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


# ---------------- perfil da unidade (advertências) ----------------

@app.route('/perfil')
@need_login
def perfil():
    """Perfil da unidade: exige unidade + código (admin gera por unidade).
    Advertências da administração só aparecem aqui."""
    uid = session.get('unidade')
    admin_preview = False
    if not uid and role() == 'admin':
        sel = request.args.get('unidade', '').upper()
        todas = [u for u, in odb().execute('SELECT unidade FROM unidades ORDER BY unidade')]
        if sel in todas:
            uid, admin_preview = sel, True
        else:
            return render_template('perfil.html', admin_pick=True, todas=todas)
    if not uid:
        msgs = {'unidade': 'Selecione bloco e apartamento.',
                'semcodigo': 'Esta unidade ainda não tem código — peça à administração.',
                'codigo': 'Código ou senha incorretos — tente novamente.'}
        return render_template(
            'perfil.html', uid=None,
            erro=msgs.get(request.args.get('erro')),
            blocos=BLOCOS, aptos=sorted(APTOS))
    conn = odb()
    fl = conn.execute(
        'SELECT em_atraso, mud_in, mud_out, idoso75, email, telefone '
        'FROM unidades WHERE unidade = ?', (uid,)).fetchone()
    advs = conn.execute(
        'SELECT criado_em, texto FROM advertencias WHERE unidade = ? ORDER BY id DESC',
        (uid,)).fetchall()
    ocs = conn.execute(
        'SELECT criado_em, categoria, texto, resolvida FROM ocorrencias '
        'WHERE unidade = ? ORDER BY id DESC LIMIT 20', (uid,)).fetchall()
    bloco, num = uid.split('-')
    flags = {'a': bool(fl[0]), 'mi': bool(fl[1]),
             'mo': bool(fl[2]), 'i': bool(fl[3])} if fl else {}
    contato = request.args.get('contato')
    return render_template('perfil.html', uid=uid, bloco=bloco, num=num,
                           admin_preview=admin_preview, flags=flags,
                           advs=advs, ocs=ocs, contato=contato,
                           email=fl[4] if fl else None,
                           fone=fmt_fone(fl[5]) if fl else '',
                           heading='Minha unidade', active='perfil')


@app.post('/perfil/acesso')
@need_login
def perfil_acesso():
    bloco = request.form.get('bloco', '').upper()
    apto = request.form.get('apto', '')
    uid = f'{bloco}-{apto}'
    if bloco not in BLOCOS or apto not in APTOS:
        return redirect('/perfil?erro=unidade')
    row = odb().execute('SELECT codigo, senha_temp FROM unidades WHERE unidade = ?',
                        (uid,)).fetchone()
    if not row or not row[0]:
        return redirect('/perfil?erro=semcodigo')
    codigo = request.form.get('codigo', '').strip()
    if not hmac.compare_digest(row[0], hashlib.sha256(codigo.encode()).hexdigest()):
        return redirect('/perfil?erro=codigo')
    session['unidade'] = uid
    if row[1]:
        session['trocar'] = 1
        return redirect('/trocar-senha')
    return redirect('/perfil')


@app.get('/perfil/sair')
@need_login
def perfil_sair():
    session.pop('unidade', None)
    return redirect('/perfil')


@app.post('/perfil/contato')
@need_login
def perfil_contato():
    """Morador atualiza o contato da própria unidade; admin também pode
    (é morador) — inclusive na pré-visualização de outra unidade."""
    uid = request.form.get('unidade', '').upper()
    if uid != session.get('unidade') and role() != 'admin':
        return {'ok': False, 'msg': 'Sem permissão.'}, 403
    conn = odb()
    if not conn.execute('SELECT 1 FROM unidades WHERE unidade = ?',
                        (uid,)).fetchone():
        return redirect('/perfil?contato=Unidade+desconhecida')
    try:
        email = norm_email(request.form.get('email'))
        fone = norm_fone(request.form.get('telefone'))
    except ValueError as e:
        return redirect('/perfil?' + urllib.parse.urlencode(
            {'unidade': uid, 'contato': str(e)}))
    conn.execute('UPDATE unidades SET email = ?, telefone = ? WHERE unidade = ?',
                 (email, fone, uid))
    conn.commit()
    return redirect(f'/perfil?unidade={uid}&contato=ok')


@app.get('/dados.js')
@need_login
def dadosjs():
    return send_from_directory(DATA_DIR, 'dados.js', mimetype='application/javascript')


@app.get('/theme.css')
def theme_css():
    # compat com links antigos → o compilado Tailwind/Preline
    return send_from_directory(BASE / 'static' / 'css', 'theme.css',
                               mimetype='text/css')


@app.get('/<path:fname>')
@need_login
def static_files(fname):
    if fname in STATIC:
        return send_from_directory(BASE, fname)
    return 'Não encontrado', 404


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000, threaded=True)
