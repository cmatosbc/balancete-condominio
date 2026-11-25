# Dashboard do Balancete — Condomínio Elit's Park

Dashboards em HTML puro (sem dependências de build) alimentados por um
banco SQLite populado a partir dos balancetes em PDF (formato
Condomínio21 / Brancalion).

## Arquivos

- `index.html` — dashboard do mês. Aceita `?mes=AAAA-MM` (padrão: mais recente)
- `historico.html` — histórico: evolução da água, receitas×despesas,
  composição das despesas, inadimplência e insights automáticos
- `dados.js` — gerado pelo `extrair.py` (`window.DADOS = {unidades, meses: {...}}`)
- `extrair.py` — parseia o PDF, grava o mês no banco, arquiva em `pdfs/`,
  regenera `dados.js`
- `balancetes.db` — SQLite; tabela `meses` (chave `ano_mes` + JSON completo)
- `pdfs/` — balancetes originais (`AAAA-MM.pdf`)
- `senha.js` — portão de senha VISUAL (não é segurança real; repo é público).
  Senha: `elitspark2026` (hash SHA-256 em `EXPECTED`).
  Trocar: `echo -n "NOVA" | sha256sum` → colar em `senha.js` → commit.
- `.github/workflows/atualizar.yml` — CI: push em `pdfs/` → extrai → commita
- `AGENTS.md` — este arquivo

## Atualização mensal

Local:
```bash
cd ~/condominio
python3 extrair.py ~/Downloads/<novo_balancete>.pdf   # ou um diretório
```

GitHub: suba o PDF para `pdfs/` (web ou git) — o workflow extrai,
commita `dados.js`/`balancetes.db` e o Pages republica
(https://cmatosbc.github.io/balancete-condominio/).

- Reimportar o mesmo mês sobrescreve o registro (idempotente).
- `python3 extrair.py --listar` mostra os meses no banco.
- Depois é só recarregar as páginas (funcionam via `file://` ou servidor).

## Verificação

```bash
node --check dados.js
python3 -m http.server 8765   # pré-visualização local
```

O `extrair.py` imprime `⚠` para cada campo não encontrado — nesse caso
o layout do PDF provavelmente mudou e o parser precisa de ajuste.

## Notas do parser (`extrair.py`)

- Usa `pdftotext -tsv` (palavras com coordenadas X/Y) e reconstrói as
  duas colunas; o layout é estável entre os meses.
- Grupos de despesa desconhecidos são detectados automaticamente
  (cabeçalho em caixa alta) e ganham cor própria.
- `UNIDADES = 144` é constante no topo do script — não consta no PDF.
- Rateio é por fração ideal: `água da unidade = taxa × (água ÷ rateio)`.
