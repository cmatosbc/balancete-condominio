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
- `app.py` — servidor Flask (Docker): login com 2 níveis — admin usa
  `ADMIN_PASSWORD` (acesso total, `/admin` + `POST /upload`); morador
  usa bloco+apto+código OU senha própria da unidade (sha256 em
  `unidades.codigo`; `session['unidade']` vinculada → voto usa a
  unidade da sessão, `/perfil` direto, selects pré-preenchidos).
  Código emitido é temporário (`senha_temp=1`): primeiro acesso cai
  no gate `before_request` → `/trocar-senha` até definir senha ≥6
  (aí `senha_temp=0` e o código velho morre). `MORADOR_PASSWORD` é
  opcional — aba "Administrador" aceita essa senha como acesso
  genérico sem unidade (transição). `SECRET_KEY` em `DATA_DIR/.secret_key`.
  `POST /admin/codigos/gerar` emite códigos para todas as unidades sem
  código e devolve a lista uma única vez (para distribuição).
  E-mail: `unidades.email` + envio via SMTP (env `SMTP_HOST/PORT/
  USER/PASS/FROM`, `PUBLIC_URL`) — `POST /admin/unidade/<id>/email`
  cadastra, `/…/email/enviar` envia código temporário (também serve
  como reset: regenera `senha_temp=1`), `POST /admin/codigos/email`
  envia em massa só para unidades com e-mail e `senha_temp=1`. Sem
  SMTP configurado, as rotas retornam 400 explicativo — vale o
  "Gerar código" manual.
  Livro de ocorrências: `/ocorrencia` (todos registram) → tabela
  `ocorrencias` → listadas no `/admin`; admin alterna `resolvida` via
  `POST /admin/ocorrencia/<id>/resolver`.
  Votações: admin publica em `/admin` (`POST /admin/proposta`,
  `POST /admin/proposta/<id>/alternar` abre/encerra) → tabela `propostas`;
  moradores votam em `/propostas` → tabela `votos`, 1 voto por unidade
  (UNIQUE proposta+unidade, votar de novo muda o voto; votos em
  propostas encerradas são rejeitados).
  Unidades: tabela `unidades` semeia as 144 (blocos A1-A3, B1-B3 ×
  andares 1-6 × aptos 1-4 → `BLOCO-ANDAR+NUM`, ex.: A3-11). Desenho
  predial no `/admin`: clique abre painel da unidade com checkboxes —
  `em_atraso` (sem voto, 403 + aviso em `/propostas`), `mud_in`,
  `mud_out`, `idoso75` (`POST /admin/unidade/<id>/flag` com
  `flag=a|mi|mo|i`). Badge âmbar na célula = nº de ocorrências abertas
  (derivado de `ocorrencias.unidade`, resolvida=0). `/api/resumo`
  devolve `mapa` só com unidades flaggeadas. Ocorrência e voto usam
  selects bloco+apto — unidade sempre válida (`APTOS`/`BLOCOS` no
  app.py); "área comum" grava unidade NULL.
  Perfil/advertências: tabela `advertencias` (unidade+texto) — visíveis
  SÓ em `/perfil`, acessado com unidade+código de 4 dígitos que o admin
  gera no painel (`POST /admin/unidade/<id>/codigo` — retorna uma vez,
  banco guarda sha256; gerar novo invalida). `session['unidade']`
  vincula a sessão ao perfil. Badge vermelho `!` no mapa = unidade
  advertida. Rotas: `POST /perfil/acesso`, `GET /perfil/sair`,
  `POST /admin/unidade/<id>/advertencia`,
  `POST /admin/advertencia/<id>/remover`.
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
