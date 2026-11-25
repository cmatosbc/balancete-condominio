# Balancetes — Condomínio Elit's Park

Dashboard público dos balancetes mensais do condomínio, gerado
automaticamente a partir dos PDFs da administradora (Condomínio21 /
Brancalion).

**Site:** https://cmatosbc.github.io/balancete-condominio/

## Como atualizar (mensal)

Basta colocar o PDF do balancete na pasta `pdfs/` — o resto é automático:

1. **Pela web (mais fácil):** no GitHub, abra a pasta `pdfs/` →
   *Add file* → *Upload files* → arraste o PDF → *Commit*.
   O nome do arquivo não importa; ele é renomeado para `AAAA-MM.pdf`.
2. **Por git:** `cp balancete.pdf pdfs/ && git add pdfs && git commit && git push`
3. **Local:** `python3 extrair.py <arquivo.pdf>` (importa e arquiva sozinho)

A cada push em `pdfs/`, o workflow
[atualizar.yml](.github/workflows/atualizar.yml) instala o poppler,
roda `extrair.py`, grava o mês no `balancetes.db`, regenera `dados.js`
e comita — o GitHub Pages republica o site em ~1 minuto.

## Arquivos

| Arquivo | Função |
|---|---|
| `index.html` | Dashboard do mês (`?mes=AAAA-MM` para meses anteriores) |
| `historico.html` | Evolução mensal e insights automáticos |
| `dados.js` | Gerado — `window.DADOS` com todos os meses |
| `extrair.py` | Parser do PDF → SQLite → `dados.js` |
| `balancetes.db` | Banco SQLite (fonte da verdade; regenerável a partir de `pdfs/`) |
| `pdfs/` | Balancetes originais arquivados como `AAAA-MM.pdf` |

## Rodando localmente

```bash
python3 -m http.server 8765   # ou abra os HTMLs direto no navegador
python3 extrair.py --listar   # meses no banco
```
