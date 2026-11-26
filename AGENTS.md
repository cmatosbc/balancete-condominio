# Dashboard do Balancete — Condomínio Elit's Park

Dashboards em HTML puro (sem dependências de build) alimentados por um
banco SQLite populado a partir dos balancetes em PDF (formato
Condomínio21 / Brancalion).

## Arquivos

- `index.html` — dashboard do mês. Aceita `?mes=AAAA-MM` (padrão: mais recente)
- `historico.html` — histórico: evolução da água, receitas×despesas,
  composição das despesas, inadimplência e insights automáticos
- `theme.css` — tokens e estilos compartilhados (paleta, tipografia,
  navegação, foco) entre páginas estáticas e telas Flask
- `dados.js` — gerado pelo `extrair.py` (`window.DADOS = {unidades, meses: {...}}`)
- `extrair.py` — parseia o PDF, grava o mês no banco, arquiva em `pdfs/`,
  regenera `dados.js`
- `balancetes.db` — SQLite; tabela `meses` (chave `ano_mes` + JSON completo).
  Cache local/CI — não é versionado (regenerável com `extrair.py pdfs`)
- `pdfs/` — balancetes originais (`AAAA-MM.pdf`)
- `senha.js` — portão de senha VISUAL para o modo estático/Pages
  (senha `elitspark2026`, hash SHA-256 em `EXPECTED`; no modo Docker o
  cookie `cond_app` pula o portão — a sessão do app é a auth real).
- `app.py` — servidor Flask (Docker): login por senha com 2 níveis
  (`ADMIN_PASSWORD`/`MORADOR_PASSWORD` no env), `/admin` + `POST /upload`
  só para admin, `SECRET_KEY` persistida em `DATA_DIR/.secret_key`.
  Livro de ocorrências: `/ocorrencia` (todos registram) → tabela
  `ocorrencias` → listadas no `/admin`; admin alterna `resolvida` via
  `POST /admin/ocorrencia/<id>/resolver`.
  Votações: admin publica em `/admin` (`POST /admin/proposta`,
  `POST /admin/proposta/<id>/alternar` abre/encerra) → tabela `propostas`;
  moradores votam em `/propostas` → tabela `votos`, 1 voto por unidade
  (UNIQUE proposta+unidade, votar de novo muda o voto; votos em
  propostas encerradas são rejeitados).
  Unidades: tabela `unidades` semeia as 144 (blocos A1-A3, B1-B3 ×
  andares 1-6 × aptos 1-4 → `BLOCO-ANDAR+NUM`, ex.: A3-11). Admin
  marca atraso no desenho predial do `/admin`
  (`POST /admin/unidade/<id>/atraso`) — unidade em atraso não vota
  (403) e `/propostas` exibe aviso. Votos só aceitam unidades do
  cadastro (formato validado server-side).
  O banco usa WAL + `busy_timeout` (concorrência entre workers
  gunicorn); `odb()` garante o schema só na 1ª chamada do processo —
  não escrever em paths de leitura, senão "database is locked".
- `Dockerfile` / `entrypoint.sh` / `docker-compose.yml` — imagem
  python+poppler+gunicorn; volume `/data`; PDFs de `pdfs/` semeiam o banco.
- `data/` — artefatos de runtime do container (gitignored).
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
