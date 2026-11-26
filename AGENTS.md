# Dashboard do Balancete — Condomínio Elit's Park

Dashboards + app Flask alimentados por um banco SQLite populado a partir
dos balancetes em PDF (formato Condomínio21 / Brancalion). A UI usa um
design system próprio sobre **Tailwind CSS 3 + Preline**, compilado em
build (não é mais CSS escrito à mão).

## Arquivos

- `index.html` — dashboard do mês. Aceita `?mes=AAAA-MM` (padrão: mais recente)
- `historico.html` — histórico: evolução da água, receitas×despesas,
  composição das despesas, inadimplência e insights automáticos.
  As duas páginas são 100% estáticas (Pages/`file://`) e consomem o CSS
  compilado + `dados.js` — sem Jinja nem toolchain no runtime.
- `templates/` — templates Jinja das telas Flask (`base.html` + nav
  `_nav.html` + login/ocorrencia/perfil/propostas/trocar/erro403/admin).
  Todo HTML de rota vive aqui — `app.py` só tem lógica/rotas e chama
  `render_template`. NUNCA volte a embutir HTML em strings Python: a
  classe de bugs `\n`/`\d` double-escape (que já quebrou o admin duas
  vezes) só existe em strings `"""` — em Jinja o JS é literal.
- `src/input.css` — fonte do design system: tokens Tailwind + classes
  de componente `ep-*` via `@apply` (ep-card, ep-btn, ep-input,
  ep-navlink, ep-apt do desenho predial, ep-hero, ep-seg, ep-barfill,
  tooltip, etc.). Edite AQUI, não no CSS compilado.
- `tailwind.config.js` — content scan em `templates/*.html` +
  `*.html` raiz + `static/js/*.js`; paleta `ink`/`brand`, fontes
  Inter/Space Grotesk, plugin `preline`.
- `static/css/theme.css` — CSS compilado e minificado, **commitado**
  (o Pages consome direto; não tem build no CI). Rota `/theme.css` no
  Flask serve este arquivo por compatibilidade.
- `static/vendor/preline.js` — runtime JS do Preline vendorado (tabs,
  overlays — usado via atributos `data-hs-*` nas templates).
- `static/js/app.js` — helpers compartilhados (`$`, `esc`, `toast`).
- `package.json` / `package-lock.json` — toolchain de build: `tailwindcss@3`,
  `preline`. `node_modules/` é gitignored.
- `dados.js` — gerado pelo `extrair.py` (`window.DADOS = {unidades, meses: {...}}`)
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
  cadastra contato (`email` e/ou `telefone`; campo ausente não muda,
  vazio limpa), `/…/email/enviar` envia código temporário (também
  serve como reset: regenera `senha_temp=1`), `POST /admin/codigos/email`
  envia em massa só para unidades com e-mail e `senha_temp=1`. Sem
  SMTP configurado, as rotas retornam 400 explicativo — vale o
  "Gerar código" manual.
  Telefone: `unidades.telefone` guarda dígitos `55+DDD+número`
  (`norm_fone`/`fmt_fone` no app.py); morador edita o próprio contato
  em `/perfil` (`POST /perfil/contato` — própria unidade ou admin).
  WhatsApp: `POST /admin/unidade/<id>/whatsapp/enviar` envia código
  temporário via Evolution API self-hosted (env `EVO_URL/KEY/INSTANCE`,
  endpoint `/message/sendText/{instance}` — body `{number, text}`;
  o formato `{textMessage:{text}}` da doc nova é REJEITADO pela
  v2.3.8 com "requires property text"). A licença da Evolution API
  (Apache 2.0 + condições) exige aviso visível a admins de que ela é
  usada — o painel da unidade mostra essa nota quando `evo=true` no
  `/api/resumo`. Sem Evolution configurada, a rota retorna 400
  explicativo e o botão fica desabilitado.
  Entrada (bidirecional): `POST /webhook/whatsapp` recebe
  `MESSAGES_UPSERT` da Evolution (configurado via `POST
  {EVO}/webhook/set/{instance}` com `url=http://site:8000/…` e
  `headers.apikey=EVO_KEY` — o endpoint valida esse header ou
  `?key=`). Telefone do remetente → unidade via `unidades.telefone`
  (JID `@lid` resolve por `senderPn`). Comandos em `_wa_comando`:
  `OCORRENCIA <texto>` (grava no livro, categoria `whatsapp`),
  `VOTACAO` (lista abertas), `VOTAR <n> FAVOR|CONTRA` (mesmas regras
  do site: unidade válida, não em atraso, proposta aberta, upsert),
  `AJUDA`; respostas por `_wa_reply` (best-effort, nunca derruba o
  webhook). Ignora fromMe/grupos/broadcast/não-texto.
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
- `Dockerfile` / `entrypoint.sh` / `docker-compose.yml` — build
  multi-stage: estágio `node:20-alpine` roda `npm ci` + compila
  `theme.css` + vendora `preline.js`; imagem final é só
  python+poppler+gunicorn (zero Node em produção); volume `/data`;
  PDFs de `pdfs/` semeiam o banco. `.dockerignore` exclui
  `node_modules/` e `data/`. WhatsApp: `docker compose --profile
  whatsapp up -d` sobe Evolution API (`evolution`, porta 8081) +
  `evopg` (sessões) + `evoredis`; chaves em `.env` (gitignored):
  `EVO_KEY` (apikey + login do `/manager`), `EVO_DB_PASS`.
- `data/` — artefatos de runtime do container (gitignored).
- `.github/workflows/atualizar.yml` — CI: push em `pdfs/` → extrai → commita
- `AGENTS.md` — este arquivo

## Build do frontend

O `theme.css` é artefato commitado. Recompile SEMPRE que mexer em
`src/input.css`, `tailwind.config.js` ou adicionar classes novas em
templates/HTMLs (o scanner pega classes em atributos e em strings JS):

```bash
npm ci                                        # 1ª vez (ou npm install)
npx tailwindcss -i src/input.css -o static/css/theme.css --minify
docker compose up -d --build                  # rebuilda a imagem
```

O estágio Node do Dockerfile repete exatamente esse passo — então
`docker compose build` basta para produção; o comando acima serve para
iterar local sem rebuildar a imagem.

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
python3 -m py_compile app.py
python3 -m http.server 8765   # pré-visualização local
```

Para checar JS de páginas servidas: baixe a página com cookie de sessão,
extraia os `<script>` inline e rode `node --check` — valide o HTML
**servido**, não o fonte do template. NÃO passe por `html.unescape`:
entidades `&#39;` dentro de `<script>` são literais corretos (o browser
não decodifica entidades ali) — unescape corrompe o check.

O `extrair.py` imprime `⚠` para cada campo não encontrado — nesse caso
o layout do PDF provavelmente mudou e o parser precisa de ajuste.

## Notas do parser (`extrair.py`)

- Usa `pdftotext -tsv` (palavras com coordenadas X/Y) e reconstrói as
  duas colunas; o layout é estável entre os meses.
- Grupos de despesa desconhecidos são detectados automaticamente
  (cabeçalho em caixa alta) e ganham cor própria.
- `UNIDADES = 144` é constante no topo do script — não consta no PDF.
- Rateio é por fração ideal: `água da unidade = taxa × (água ÷ rateio)`.
