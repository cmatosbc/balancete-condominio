#!/usr/bin/env python3
"""
Extrai os dados do balancete em PDF (formato Condomínio21 / Brancalion),
grava o mês no banco SQLite (balancetes.db) e regenera dados.js com o
histórico completo usado por index.html e historico.html.

Uso:
    python3 extrair.py <balancete.pdf>   # importa um mês e arquiva em pdfs/
    python3 extrair.py <diretorio>       # importa todos os PDFs do diretório
    python3 extrair.py --listar          # lista meses no banco

Requer: pdftotext (poppler-utils).
"""
import csv
import io
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import unicodedata
from pathlib import Path

UNIDADES = 144  # nº de unidades do condomínio (não consta no PDF)
DATA_DIR = Path(os.environ.get("DATA_DIR", Path(__file__).parent))
DB = DATA_DIR / "balancetes.db"
DADOSJS = DATA_DIR / "dados.js"
PDFS = DATA_DIR / "pdfs"

NUM_RE = re.compile(r"^\(?-?[\d.]*\d,\d{2}\)?%?$")
MESES = ["", "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
         "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"]

CORES = {
    "pessoal": "#8b5cf6", "tarifas": "#38bdf8", "extra": "#f59e0b",
    "admin": "#f472b6", "manut": "#34d399", "elev": "#a3e635", "gas": "#fb7185",
}
GRUPO_HEADERS = {
    "DESPESAS COM PESSOAL": ("pessoal", "Pessoal"),
    "TARIFAS PUBLICAS": ("tarifas", "Tarifas públicas"),
    "DESPESA EXTRAORDINARIA": ("extra", "Desp. extraordinárias"),
    "ADMINISTRATIVAS": ("admin", "Administrativas"),
    "MANUTENCAO": ("manut", "Manutenção"),
    "ELEVADORES": ("elev", "Elevadores"),
    "GAS": ("gas", "Gás"),
}
ALIAS = {
    "AGUA": "Água (consumo)",
    "AGUA MINERAL": "Água mineral",
    "BOMBA D´AGUA": "Bomba d'água",
    "BOMBA D'AGUA": "Bomba d'água",
    "HIDRAULICA/ENCANADOR": "Hidráulica/encanador",
    "SALARIO(S) FUNCIONARIOS(AS)": "Salários",
    "FERIAS": "Férias (funcionários)",
    "FUNDO 13º/FERIAS": "Fundo 13º/Férias",
    "CESTA BASICA DOS FUNCIONARIOS": "Cesta básica",
    "CONTRIBUICAO ASSIST. FUNCIONARIOS": "Contrib. assist. funcionários",
    "MEDICINA OCUPACIONAL": "Medicina ocupacional",
    "CONVENIO MEDICO DOS FUNCIONARIOS": "Convênio médico",
    "PENSAO ALIMENTICIA": "Pensão alimentícia",
    "USECRED - REDE AMPLA": "Usecred - Rede Ampla",
    "BENEFICIO SOCIAL CCT": "Benefício social CCT",
    "EMPRESTIMO CONSIGNADO -JA DESC. EM FOLHA": "Empréstimo consignado",
    "PIS - FOLHA DE PAGAMENTO": "PIS folha de pagamento",
    "FGTS - SALARIO": "FGTS",
    "ADIANTAMENTO SALARIAL": "Adiantamento salarial",
    "MANUTENCAO EQUIP. CONTRA INCENDIO": "Equip. contra incêndio",
    "SISTEMA DE SEGURANCA": "Sistema de segurança",
    "MATERIAIS DE LIMPEZA": "Materiais de limpeza",
    "MATERIAL ELETRICO": "Material elétrico",
    "MANUTENCAO DO JARDIM": "Manutenção do jardim",
    "MONITORAMENTO ELETRONICO": "Monitoramento eletrônico",
    "DEDETIZACAO": "Dedetização",
    "AQUISICAO DE GAS": "Aquisição de gás",
    "LAUDO DE ESTANQUEIDADE": "Laudo de estanqueidade",
    "SEGURO OBRIGATORIO (PATRIMONIAL)": "Seguro obrigatório",
    "MATERIAL DE MANUTENCAO": "Material de manutenção",
    "MANUTENCAO FILTRO": "Manutenção filtro",
    "DESPESAS CARTORARIAS": "Despesas cartorárias",
    "TARIFAS BANCARIAS GERAIS": "Tarifas bancárias",
    "MATERIAL DE ESCRITORIO": "Material de escritório",
    "PINTURA": "Pintura (fachada)",
    "UTILIZACAO DO SALAO DE FESTAS": "Salão de festas",
    "REEMBOLSO CUSTAS PROCESSUAIS": "Reembolso custas",
    "MULTA/JUROS/CORRECAO RECEB. JUDICIAL": "Multa/juros judicial",
    "GARAGEM": "Garagem (obra extra)",
    "DIVERSOS": "Diversos (extra)",
    "AJUDA DE CUSTOS SINDICO(A)": "Ajuda de custos síndico",
    "AJUDA DE CUSTOS SUB-SINDICO(A)": "Ajuda de custos sub-síndico",
    "TARIFA DE COBRANCA": "Tarifa de cobrança",
    "EXTRA PROPRIETARIO": "Extra proprietário",
    "RENDIMENTOS DE APLICACAO FINANCEIRA": "Rendimentos aplic.",
    "CONTROLE PORTAO/CARTAO DE ACESSO/TAG": "Cartões/tags de acesso",
    "ENERGIA ELETRICA": "Energia elétrica",
}
MINUSC = {"DE", "DA", "DO", "DOS", "DAS", "E", "EM", "COM", "PARA"}
CONTA_ALIAS = {
    "CONTA CORRENTE 13 002229-0": "Conta corrente …2229-0",
    "POUP. 60 003115-3 F. RESERVA": "Poupança …115-3 · Fundo de reserva",
    "POUP. 60 003394-2 FERIAS 13º": "Poupança …394-2 · Férias/13º",
    "POUP. 60 003395-9 GARAGEM": "Poupança …395-9 · Garagem",
    "POUP 60 012388-5 RESERVA C/C": "Poupança …388-5 · Reserva",
    "APLIC. CDB DI - PINTURA": "CDB DI · Pintura",
    "APLIC. DI TOP - CH. EXTRA": "Aplic. DI · Ch. Extra",
}


FALLBACK_CORES = ["#22d3ee", "#e879f9", "#facc15", "#4ade80", "#fca5a5", "#c4b5fd"]
EXCL_HDR = ("RECIBO", "RESUMO", "CONDOMINIO", "INTERNET", "WWW", "IDENTIFICADOR",
            "BOLETO", "MENSAGEM", "CORREIO", "PAGADOR", "SEU CONDOMINIO")
STOP_TXT = ("RESUMO", "CONTAS CORRENTES", "MENSAGEM", "COMPOSICAO",
            "IDENTIFICADOR", "BOLETO DE COBRANCA")


def is_group_header(t, nxt):
    """Texto em CAIXA ALTA sem dígitos, seguido de item/valor → novo grupo de despesa."""
    if not t or t != t.upper() or len(t) < 3 or any(c.isdigit() for c in t):
        return False
    if any(k in norm(t) for k in EXCL_HDR):
        return False
    return nxt is not None and nxt[0] in ("item", "num")


def novo_grupo(label, grupos):
    base = re.sub(r"[^A-Z0-9]+", "_", norm(label)).strip("_").lower() or "outros"
    key, i = base, 2
    while key in grupos:
        key = f"{base}{i}"
        i += 1
    cor = FALLBACK_CORES[(len(grupos)) % len(FALLBACK_CORES)]
    return key, {"key": key, "nome": pretty(label), "cor": cor, "valor": 0, "itens": []}


def pretty_conta(s):
    s = re.sub(r"^\d+-", "", s).strip()
    if norm(s) in CONTA_ALIAS:
        return CONTA_ALIAS[norm(s)]
    m = re.search(r"0*(\d{4,5}-\d)", s)
    tail = " …" + m.group(1) if m else ""
    s = re.sub(r"\d{2}\s+0*\d{4,6}-\d", "", s).strip()
    return s.title() + tail


def norm(s):
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s).strip().upper()


def brl(tok):
    neg = tok.startswith("(") or tok.startswith("-")
    tok = tok.strip("()%")
    v = float(tok.replace(".", "").replace(",", "."))
    return -v if neg else v


def _akey(s):
    return norm(s).replace("´", "").replace("`", "").replace("'", "")


_ALIAS_N = {_akey(k): v for k, v in ALIAS.items()}


def pretty(s):
    key = _akey(s)
    if key in _ALIAS_N:
        return _ALIAS_N[key]
    out = []
    for i, w in enumerate(s.split()):
        out.append(w.lower() if i > 0 and norm(w) in MINUSC else w.capitalize())
    return " ".join(out)


def load_words(pdf):
    r = subprocess.run(["pdftotext", "-tsv", str(pdf), "-"],
                       capture_output=True, text=True, check=True)
    words = []
    for row in csv.DictReader(io.StringIO(r.stdout), delimiter="\t"):
        if row["level"] == "5":
            words.append({"pg": int(row["page_num"]), "x": float(row["left"]),
                          "y": float(row["top"]), "t": row["text"]})
    return words


def rows_of(words):
    """Agrupa palavras em linhas (topo com tolerância 1.3pt)."""
    rows, last_y = [], None
    for w in sorted(words, key=lambda w: (w["y"], w["x"])):
        if last_y is None or w["y"] - last_y > 1.3:
            rows.append([])
        rows[-1].append(w)
        last_y = w["y"]
    return rows


def events(rows):
    """
    Converte linhas em eventos:
      ('item', label, [valores])  — rótulo + números (mesma linha ou linha adjacente)
      ('num', [valores], y)       — linha só de números (subtotais)
      ('text', texto, y)          — linha só de texto (cabeçalhos)
    """
    evs = []
    for r in rows:
        r.sort(key=lambda w: w["x"])
        toks = [w["t"] for w in r]
        ni = [i for i, t in enumerate(toks) if NUM_RE.match(t)]
        if ni and ni[0] > 0:
            evs.append(("item", " ".join(toks[:ni[0]]),
                        [brl(t) for t in toks[ni[0]:] if NUM_RE.match(t)]))
        elif ni:
            vals = [brl(toks[i]) for i in ni]
            if evs and evs[-1][0] == "text" and r[0]["y"] - evs[-1][2] < 2.6:
                evs[-1] = ("item", evs[-1][1], vals)
            else:
                evs.append(("num", vals, r[0]["y"]))
        else:
            evs.append(("text", " ".join(toks), r[0]["y"]))
    return evs


def col_events(words, pg, xmin, xmax, ymax=1e9):
    sel = [w for w in words if w["pg"] == pg and xmin <= w["x"] < xmax and w["y"] < ymax]
    return events(rows_of(sel))


def parse_pdf(pdf):
    words = load_words(pdf)
    avisos = []
    dados = {"unidades": UNIDADES}

    # ---------- período / condomínio (título) ----------
    titulo = " ".join(w["t"] for w in words if w["pg"] == 1 and w["y"] < 20)
    m = re.search(r"(.+?) - BALANCETE.*?- (\d{2}/\d{2}/\d{4}) a (\d{2}/\d{2}/\d{4})", titulo)
    if m:
        dados["condominio"] = m.group(1).title().replace("`S", "'s").replace("´S", "'s")
        dados["periodo"] = f"{m.group(2)} a {m.group(3)}"
        dados["mesLabel"] = MESES[int(m.group(2)[3:5])] + "/" + m.group(2)[6:]
    doc = re.search(r"\b([A-Z]+\d+-\d+/\d+)\b", " ".join(
        " ".join(w["t"] for w in words if w["pg"] == p) for p in {1, 2}))
    if doc:
        dados["docId"] = doc.group(1)

    # ---------- eventos por coluna (corte em x=290) ----------
    ev_esq = col_events(words, 1, 0, 290)
    ev_dir = col_events(words, 1, 290, 1e9)

    # ---------- coluna esquerda: receitas, despesas, composição ----------
    receitas, modo, comp = [], "receitas", {}
    grupos, cur = {}, None
    for i, (kind, a, b) in enumerate(ev_esq):
        n = norm(a) if kind in ("item", "text") else ""
        nxt = ev_esq[i + 1] if i + 1 < len(ev_esq) else None
        if kind == "text":
            if n == "DESPESAS":
                modo = "despesas"
            elif n.startswith("COMPOSICAO DA ARRECADACAO"):
                modo = "composicao"
            elif modo == "despesas" and n in GRUPO_HEADERS:
                key, nome = GRUPO_HEADERS[n]
                cur = grupos.setdefault(key, {"key": key, "nome": nome,
                                              "cor": CORES[key], "valor": 0, "itens": []})
            elif modo == "despesas" and is_group_header(a, nxt):
                key, g = novo_grupo(a, grupos)
                cur = grupos.setdefault(key, g)
            continue
        if kind == "num":
            if modo == "despesas" and cur is not None and not cur["valor"]:
                cur["valor"] = a[0]
            continue
        # item
        vals = b
        if modo == "receitas":
            if n == "TOTAL RECEITAS":
                dados.setdefault("totais", {})["receitas"] = vals[0]
            elif "RECEITA" not in n:
                receitas.append([pretty(a), vals[0]])
        elif modo == "despesas" and cur is not None:
            cur["itens"].append([pretty(a), vals[0]])
        elif modo == "composicao":
            if "TAXA DE CONDOMINIO" in n:
                comp["taxa"] = vals[0]
            elif "FUNDO DE RESERVA" in n:
                comp["fundo"] = vals[0]
    # composição: rótulos na col. esquerda, valores podem estar na direita —
    # reanalisa a faixa com linhas de largura total
    comp_y = next((e[2] for e in ev_esq if e[0] == "text"
                   and norm(e[1]).startswith("COMPOSICAO DA ARRECADACAO")), None)
    if comp_y is not None:
        rws = [r for r in rows_of([w for w in words if w["pg"] == 1])
               if comp_y < r[0]["y"] < comp_y + 60]
        for e in events(rws):
            if e[0] != "item":
                continue
            nn = norm(e[1])
            if "TAXA DE CONDOMINIO" in nn:
                comp["taxa"] = e[2][0]
            elif "FUNDO DE RESERVA" in nn:
                comp["fundo"] = e[2][0]
    dados["boleto"] = comp

    # ---------- coluna direita (topo): continuação das despesas ----------
    # A coluna direita continua a lista de despesas até TOTAL DESPESAS / RESUMO.
    for i, e in enumerate(ev_dir):
        kind = e[0]
        nxt = ev_dir[i + 1] if i + 1 < len(ev_dir) else None
        if kind == "text":
            n = norm(e[1])
            if any(s in n for s in STOP_TXT):
                break
            if n in GRUPO_HEADERS:
                key, nome = GRUPO_HEADERS[n]
                cur = grupos.setdefault(key, {"key": key, "nome": nome,
                                              "cor": CORES[key], "valor": 0, "itens": []})
            elif is_group_header(e[1], nxt):
                key, g = novo_grupo(e[1], grupos)
                cur = grupos.setdefault(key, g)
        elif kind == "num":
            if cur is not None and not cur["valor"]:
                cur["valor"] = e[1][0]
        else:  # item
            n = norm(e[1])
            if n == "TOTAL DESPESAS":
                dados["totais"]["despesas"] = e[2][0]
                break
            if cur is None:
                cur = grupos.setdefault("outros", {"key": "outros", "nome": "Outros",
                                                   "cor": "#94a3b8", "valor": 0, "itens": []})
            cur["itens"].append([pretty(e[1]), e[2][0]])

    dados["grupos"] = list(grupos.values())
    dados["receitas"] = receitas

    # ---------- resumo: 1ª linha com ≥5 números após TOTAL RECEITAS ----------
    # (a linha do resumo pode fundir com um item da coluna esquerda e virar 'item')
    ev_p1_all = events(rows_of([w for w in words if w["pg"] == 1 and w["y"] < 300]))
    seen_total = False
    for e in ev_p1_all:
        vals = e[2] if e[0] == "item" else e[1] if e[0] == "num" else []
        if e[0] == "item" and norm(e[1]) == "TOTAL RECEITAS":
            seen_total = True
        elif seen_total and len(vals) >= 5:
            dados["totais"].update({"saldoMes": vals[-2], "saldoContas": vals[-1]})
            break

    # ---------- contas correntes (coluna direita: nome N-... seguido de linha numérica) ----------
    contas = []
    for i, e in enumerate(ev_dir):
        if e[0] == "text" and re.match(r"^\d+-", e[1]):
            nums = next((ev for ev in ev_dir[i + 1:] if ev[0] == "num"), None)
            if nums and len(nums[1]) >= 5:
                transf, saldo = nums[1][3], nums[1][4]
                if transf:
                    v = f"{abs(transf):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                    mov = f"{'+' if transf > 0 else '−'}{v} transf."
                else:
                    mov = "sem movimento"
                contas.append({"nome": pretty_conta(e[1]), "saldo": saldo, "mov": mov})
    dados["contas"] = contas

    # ---------- página 2: mensagem / rateio / inadimplência ----------
    linhas_p2 = [" ".join(w["t"] for w in sorted(r, key=lambda w: w["x"]))
                 for r in rows_of([w for w in words if w["pg"] == 2])]
    for t in linhas_p2:
        tn = norm(t)
        if "ORDINARIAS P/ RATEIO" in tn:
            dados["rateio"] = brl(re.search(r"R\$\s*([\d.,]+)", t).group(1))
        elif tn.startswith("TOTAL DAS DESP. ORDINARIAS") and "R$" in t:
            dados["despOrdinarias"] = brl(re.search(r"R\$\s*([\d.,]+)", t).group(1))
        elif tn.startswith("TOTAL DAS DESP. EXTRAS") and "R$" in t:
            dados["despExtras"] = brl(re.search(r"R\$\s*([\d.,]+)", t).group(1))
        elif "FUNDO DE RESERVA" in tn and "RATEIO" not in tn and "R$" in t:
            m2 = re.search(r"R\$\s*([\d.,]+)\s*$", t)
            if m2:
                dados["fundoRateio"] = brl(m2.group(1))
        elif "DEFICIT DO MES" in tn:
            v = brl(re.search(r"R\$\s*([\d.,]+)", t).group(1))
            if v:
                dados["resultado"] = {"tipo": "déficit", "valor": v}
        elif "SUPERAVIT DO MES" in tn:
            v = brl(re.search(r"R\$\s*([\d.,]+)", t).group(1))
            if v:
                dados["resultado"] = {"tipo": "superávit", "valor": v}
        elif "SEMAE" in tn:
            m2 = re.search(r"R\$\s*([\d.,]+)\s*(.*)", t)
            if m2:
                dados["semae"] = {"valor": brl(m2.group(1)),
                                  "sinal": "-" if "(-)" in t else "+",
                                  "desc": re.sub(r"\s+", " ", m2.group(2)).strip()}
        elif "APARTAMENTOS" in tn and "TAXA COND" in tn:
            m2 = re.search(r"(\d+)\s+Apartamentos\s+R\$\s*([\d.,]+)", t)
            if m2:
                dados.setdefault("inadimplencia", []).append(
                    {"aptos": int(m2.group(1)), "valor": brl(m2.group(2)), "tipo": "Taxa Cond."})
        elif "APARTAMENTOS" in tn and "CH. EXTRA" in tn:
            m2 = re.search(r"(\d+)\s+Apartamentos\s+R\$\s*([\d.,]+)", t)
            if m2:
                dados.setdefault("inadimplencia", []).append(
                    {"aptos": int(m2.group(1)), "valor": brl(m2.group(2)), "tipo": "Ch. Extra"})

    # ---------- água: consumo + itens relacionados ----------
    agua, agua_extras = 0, []
    for g in dados["grupos"]:
        for nome, v in g["itens"]:
            nn = norm(nome)
            if g["key"] == "tarifas" and nn in ("AGUA (CONSUMO)", "AGUA"):
                agua = v
            elif re.search(r"AGUA|HIDRAULIC|BOMBA", nn):
                agua_extras.append([nome, v])
    dados["agua"] = agua
    dados["aguaExtras"] = agua_extras

    # ---------- validações ----------
    soma = sum(g["valor"] for g in dados["grupos"])
    if "despesas" not in dados.get("totais", {}):
        avisos.append("TOTAL DESPESAS não encontrado")
    elif abs(soma - dados["totais"]["despesas"]) > 1:
        avisos.append(f"soma dos grupos {soma:,.2f} ≠ total despesas {dados['totais']['despesas']:,.2f}")
    if not agua:
        avisos.append("item AGUA não encontrado nas tarifas públicas")
    for c in ("rateio", "fundoRateio", "despOrdinarias"):
        if c not in dados:
            avisos.append(f"'{c}' não extraído da página 2")
    for c in ("taxa", "fundo"):
        if c not in dados.get("boleto", {}):
            avisos.append(f"composição da arrecadação: '{c}' não extraído")
    for c in ("saldoMes", "saldoContas"):
        if c not in dados.get("totais", {}):
            avisos.append(f"resumo: '{c}' não extraído")

    return dados, avisos


# ---------------- banco de dados + geração do dados.js ----------------

def ano_mes(d):
    """'01/03/2026 a 31/03/2026' -> '2026-03'"""
    ini = d["periodo"].split(" a ")[0]
    return f"{ini[6:]}-{ini[3:5]}"


def db_conn():
    conn = sqlite3.connect(DB)
    conn.execute("""CREATE TABLE IF NOT EXISTS meses (
        ano_mes TEXT PRIMARY KEY, mes_label TEXT, periodo TEXT,
        receitas REAL, despesas REAL, agua REAL, rateio REAL,
        saldo_mes REAL, dados TEXT)""")
    return conn


def db_upsert(conn, dados):
    am = ano_mes(dados)
    t = dados["totais"]
    conn.execute(
        "INSERT OR REPLACE INTO meses VALUES (?,?,?,?,?,?,?,?,?)",
        (am, dados.get("mesLabel"), dados.get("periodo"), t.get("receitas"),
         t.get("despesas"), dados.get("agua"), dados.get("rateio"),
         t.get("saldoMes"), json.dumps(dados, ensure_ascii=False)))
    conn.commit()
    return am


def regenerate_js(conn):
    rows = conn.execute("SELECT ano_mes, dados FROM meses ORDER BY ano_mes").fetchall()
    meses = {am: json.loads(txt) for am, txt in rows}
    DADOSJS.write_text("window.DADOS = " + json.dumps(
        {"unidades": UNIDADES, "meses": meses}, ensure_ascii=False) + ";\n")
    return meses


def archive_pdf(pdf, am):
    """Arquiva o PDF como pdfs/AAAA-MM.pdf (idempotente)."""
    dest = PDFS / f"{am}.pdf"
    try:
        if pdf.resolve() == dest.resolve():
            return dest
    except OSError:
        pass
    PDFS.mkdir(exist_ok=True)
    shutil.copy2(pdf, dest)
    return dest


def import_pdf(conn, pdf):
    dados, avisos = parse_pdf(pdf)
    am = db_upsert(conn, dados)
    dest = archive_pdf(pdf, am)
    agua = dados.get("agua", 0)
    print(f"✓ {dados.get('mesLabel','?')} [{am}] → {dest.name} | "
          f"receitas {dados['totais']['receitas']:,.2f} | "
          f"despesas {dados['totais']['despesas']:,.2f} | água {agua:,.2f}")
    for a in avisos:
        print("⚠", a)


def main():
    conn = db_conn()
    if len(sys.argv) > 1 and sys.argv[1] == "--listar":
        for am, ml, rec, desp, ag in conn.execute(
                "SELECT ano_mes, mes_label, receitas, despesas, agua FROM meses ORDER BY ano_mes"):
            print(f"{am}  {ml:16}  rec {rec:>12,.2f}  desp {desp:>12,.2f}  água {ag:>11,.2f}")
        return

    alvo = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    if not alvo or not alvo.exists():
        sys.exit("Uso: python3 extrair.py <balancete.pdf|diretorio> | --listar")
    pdfs = sorted(alvo.glob("*.pdf")) if alvo.is_dir() else [alvo]
    if not pdfs:
        sys.exit(f"Nenhum PDF em {alvo}")
    for pdf in pdfs:
        import_pdf(conn, pdf)
    print(f"→ {len(regenerate_js(conn))} mês(es) no banco · dados.js atualizado")


if __name__ == "__main__":
    main()
