# WordCraft Workspace no Next.js (Issue #137)

Estado em 30/10/2026. Este documento é o mapa da entrega 1 do workspace:
o que existe, o que fica com quem, e o que falta para o canário.

## O que existe

```
navegador                      web (Next, BFF)                    api (FastAPI)                       banco
─────────                      ───────────────                    ─────────────                       ─────
host.mjs (do Codex)  ──lote──▶ server action enviarEventos ──▶ POST /documentos/{id}/sessoes/{i}/eventos
  canvas eframe/WASM           (token da sessão)                   Ponte (src.wordcraft_protocol)
  ◀── event_ack, ack, ─────────────────────────────────────────── receber_lote → checkpoint?
      revision, control                                            DocumentoService.checkpoint ───────▶ documento_editor_checkpoint
                                                                   (só dentro de escrita_documental)     (service_role, CAS)
                                                                   confirmar_checkpoint ◀── recibo
```

- **Rota** `/app/processos/[id]/documentos/[documentoId]/editar`. A página
  confere processo e documento no servidor; a sessão abre no navegador,
  depois da montagem (abrir pode importar o texto legado — efeito colateral
  não roda em renderização nem em prefetch).
- **Casca em modo de trabalho** (`AppShell workspace`): tela inteira,
  `100dvh`, sem a coluna de 1200 px, sem rolagem da página, barra lateral
  recolhida ao entrar (a pessoa pode abrir).
- **`DocumentWorkspace`** (template novo do design system): barra do
  documento (voltar, sigla, título, situação, revisão, salvamento anunciado
  por leitor de tela, ações), área do editor sem cartão, painel opcional
  (Revisão e aprovação; Histórico de revisões), modo foco. Abrir painel,
  entrar em foco e redimensionar só mudam a grade: a área do documento é o
  mesmo nó, e o host nativo dentro dela não é recriado.
- **Host nativo** servido como estático com hash no nome
  (`public/app/wordcraft-host/host.<sha16>.mjs`), cópia exata de
  `assets/wordcraft_editor/host.mjs` — `tests/wordcraft-host.test.ts`
  reprova se divergir; `node scripts/sincronizar-wordcraft-host.mjs`
  regenera. O JS/WASM aprovado sai de `/app/static/wordcraft/` (mesmo
  artefato e manifesto do Streamlit), na mesma origem da página: depois do
  corte do `/`, o `Caddyfile.govconect` serve direto da pasta do release, sem
  passar pelo Streamlit. O host recusa qualquer outro caminho ou origem.
- **Tamanho dinâmico**: `lib/wordcraft/host-nativo.ts` mede a área com
  `ResizeObserver` e grava largura/altura do canvas em px CSS alinhados ao
  `devicePixelRatio` (e reage a mudança de DPR, como zoom do navegador).
  Sem reinstanciar.
- **Transporte** (`lib/wordcraft/transporte.ts`): a mesma troca do
  componente v2 do Streamlit (`setStateValue("edit", {events})` →
  `event_ack`), por HTTP. Um lote em voo; recusa da ponte (409) ou sessão
  encerrada (404) param e mostram "Reabrir"; rede/503 tentam de novo.
- **CSP**: só a rota do editor ganha `'wasm-unsafe-eval'`.
- **API** `documentos_nativos.py` (contrato em `openapi.v1.json`):

| Rota | O que faz |
|---|---|
| `GET /processos/{id}/documentos` | nativos e legados importáveis, com o id determinístico do Streamlit |
| `POST /documentos/{id}/sessoes` | revisão persistida + ponte nova (importa o legado uma vez, se preciso) |
| `POST …/sessoes/{i}/eventos` | lote do host; checkpoint → commit CAS → ACK |
| `GET …/sessoes/{i}`, `DELETE …/sessoes/{i}` | estado / encerrar |
| `POST …/sessoes/{i}/bloqueio`, `…/liberacao` | congelar o canvas na revisão salva / voltar a editar |
| `POST …/sessoes/{i}/aprovacao` | aprova a revisão EXATA que a ponte provou congelada |
| `GET /documentos/{id}/historico` | revisões imutáveis (50) |
| `POST /documentos/{id}/restauracao` | revisão antiga vira revisão nova (CAS) e o canvas reabre |
| `GET /documentos/{id}/exportacao` | DOCX/PDF do motor, da revisão persistida pedida (409 se mudou) |

Ativação: `GOVCONECT_WORDCRAFT_WORKSPACE` (ambiente da API, corte global) **e**
o tenant no canário `wordcraft_editor` (`tenant_modulos`). Fora disso, 404.

Segurança: JWT verificado; tenant, processo, revisão e status só do
servidor; a ponte de cada canvas é do par (auth_user_id, tenant) que a
abriu — outra conta recebe 404; o processo é conferido pelo RLS antes do
motor carregar. Provas: `apps/api/tests/test_documentos_nativos.py` e
`apps/api/tests_rls/test_rls_documentos.py` (pilha real).

## Divisão Claude Code × Codex (Issue #137, item 6)

| Peça | Dono | Nesta entrega |
|---|---|---|
| `assets/wordcraft_editor/host.mjs`, `validate.mjs` | Codex | intocados (só copiados para o estático do web) |
| `src/documentos_editor.py`, `src/wordcraft_*.py`, `integrations/wordcraft/**`, migrações `20261015*`–`20261018*` | Codex | intocados |
| `src/ui/wordcraft_editor.py` (limites 720/800 px do Streamlit) | Codex | intocado — "nada novo no Streamlit" |
| Página Next, `DocumentWorkspace`, transporte, BFF, API, deploy, Playwright | Claude Code | feito |

Mudanças fora das duas áreas, pequenas e necessárias para a API carregar o
dono documental sem o Streamlit: `src/qualidade.py`, `src/achados.py` e
`src/consistencia.py` passam a importar `st` de `streamlit_opcional` (no app
é o mesmo módulo); `src/db.py` ganha `CLIENTE_DOCUMENTAL` (ADR-011).

**Pedido ao Codex:** o host ainda cria o canvas com `height:720px` inline e
o Next o sobrescreve por fora. Validar no motor (eframe) o redimensionamento
contínuo, DPR fracionário e zoom em 1440/1920/768, e — se fizer sentido —
expor no host um modo "tamanho do contêiner" para a integração Streamlit
também largar os 720/800 px.

## O que falta para o canário (em ordem)

1. **Chave da ADR-011** (decisão aceita em 30/10; falta o operador criar a
   chave e gravá-la no `api.env`). Sem ela o editor abre, lê e exporta; não
   salva.
2. **Imagem da API com Node** (feito no `Dockerfile.api`) e o volume do
   runtime aprovado (feito no compose) — promover pela esteira
   (`govconect-imagens.yml` → `promover_govconect.sh`).
3. `api.env`: `GOVCONECT_WORDCRAFT_WORKSPACE=1` e as quatro
   `GOVDOCS_WORDCRAFT_*` (as mesmas do Streamlit, ver RUNBOOK_P06 §2).
4. Tenant canário: já é o mesmo `wordcraft_editor` do Streamlit.
5. **Ponta a ponta em processo sintético** (nunca documento administrativo
   real): abrir DFD, editar, ver "Salvo · revisão N" (ACK), recarregar e
   reler a mesma revisão, abrir em duas abas e provocar o conflito,
   redimensionar 1920→768 sem perder seleção/Undo, zoom, tabela longa,
   exportar DOCX e PDF, bloquear e aprovar, restaurar. Capturas lado a
   lado com o Streamlit.
6. Ondas: ligar `wordcraft_editor` para mais tenants só depois do aceite.
   Rollback: `GOVCONECT_WORDCRAFT_WORKSPACE` vazio (rota some) ou imagem
   anterior por SHA. O editor do Streamlit continua até o corte.

## Limites conhecidos

- Sessão do editor em memória do processo da API (1 worker). Reinício da
  API = "Sessão encerrada, reabra"; o rascunho não confirmado fica no
  canvas, nada persistido se perde.
- Emissão oficial: a API já tem `GET /processos/{id}/emissao/prontidao`,
  `POST /processos/{id}/emissao`, `GET …/emissao` e `…/emissao/pacote`. Ainda
  não há tela nem BFF (frente M3): até lá ela segue no Streamlit.
- Painéis de GovBot, auditoria contextual, pareceres, evidências e
  templates do Streamlit não foram trazidos: a API v1 não os expõe ainda, e
  a tela não mostra botão sem ação.
- Celular (< 768 px na abertura): leitura segura por exportação; a edição
  nativa por toque não foi comprovada.
