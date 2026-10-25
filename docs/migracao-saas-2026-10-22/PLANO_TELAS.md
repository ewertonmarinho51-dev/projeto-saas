# Plano de migração das telas — Streamlit → Gov Conect 2.0 (24/10/2026)

Pedido do operador: migrar todas as telas e funcionalidades que ainda só
existem no Streamlit, com autorização para PR, merge, deploy e produção.
Este arquivo é o mapa da frente; cada fatia vira um PR próprio, com CI
verde antes do merge e promoção por SHA (`promover_govconect.sh`).

## O que já está na interface nova

| Streamlit | Web (`apps/web`) + API (`apps/api`) |
|---|---|
| `login.py` (entrar, recuperar) | `/entrar`, `/entrar/recuperar`, `/auth/confirmar`, `/app/conta/senha` |
| `processos_ui.py` (painel) | `/app/processos` (lista, criar), `/app/processos/<id>` (nome, órgão, objeto) |
| `precos_ui.py` / `cotacoes_ui.py` | `/app/precos/*`: criar, importar, coleta, cesta, concluir/reabrir, emissão, aplicar ao processo |

## O que falta, na ordem de dependência

| Fatia | Streamlit | O que entra | Reaproveita | Bloqueio / risco |
|---|---|---|---|---|
| **M1** | `steps.render_formulario` | Formulário Matriz completo (11 campos, planilha de itens com importação XLSX e modelo, memorando por arquivo), rascunho e "iniciar elaboração"; descarte da cadeia documental quando os dados mudam, com confirmação | `config.CAMPOS_FORMULARIO`, `planilha`, `rag.extrair_texto`, `precos.aplicacao.descartar_por_planilha` | regeneração parcial (`regeneracao`) não entra: na API, dado alterado descarta como com a flag desligada — mais conservador, nunca deixa documento afirmando dado velho |
| **M2** | `steps.render_etapa_documento`, `revisao` | gerar DFD, ETP, Mapa de Riscos, TR (IA) e edital/ARP (catálogo) por job; ler; editar o texto; aprovar e reprovar na sequência; invalidar a partir do documento editado | `llm.gerar_documento`, `validacao`, `operacao_documento`, `config.sequencia_do_processo` | `src/llm.py` importa o Streamlit (desacoplar como o `db.py`); o worker precisa das chaves de IA no ambiente dele — ato do operador no servidor. Editor WordCraft fica fora (P05 BLOQUEADO, outra frente): edição em texto simples |
| **M3** | `steps.render_sucesso`, `signatarios`, `revisao.emissao_liberada` | conferência antes da emissão, signatários, exportação DOCX/PDF/ZIP com a identidade visual | `export`, `emissao`, `assinaturas`, `branding` | PDF depende do LibreOffice da imagem |
| **M4** | `demanda_ui` | Consolidar Demandas (DFDs das secretarias → planilha) e aplicar ao processo | `demanda.*` (puros) | — |
| **M5** | `parecer_ui` | Parecer Jurídico: anexar, plano de correção, aplicar, diff | `pareceres`, `parecer_correcao` | depende de M2 |
| **M6** | `biblioteca` | Base de Conhecimento (admin): enviar, indexar, listar, excluir | `rag` | embeddings pinados em `text-embedding-3-small`; chave no worker |
| **M7** | `admin`, `instituicional` | Administração: usuários e papéis, secretarias, identidade visual e timbrado, servidores e portarias, flags | `auth`, `branding`, `instituicional_bridge`, `assinaturas` | criar/desativar usuário exige a Admin API (credencial de servidor) — rota só de admin, revisada pelo `revisor-de-banco-e-seguranca`. Chaves de IA **não** vão para a tela nova: ficam no ambiente |
| **M8** | `governanca_ui` | Centro de Governança: catálogo de cláusulas, políticas, famílias, templates, herança, pareceres | `catalogo`, `politicas`, `familias`, `templates_gov` | flag + papel de governança |
| **M9** | `govbot_panel` | GovBot: conversa com contexto e citações, propostas aplicáveis ao documento | `govbot`, `blocos`, `fatos` | depende de M2 |
| **M10** | `cotacoes_ui` | o que a tela unificada de cotações tem e `/app/precos` ainda não | `precos.*` | auditar a paridade antes de escrever |

Fora desta frente, de propósito: editor WordCraft (`wordcraft_*`, outra
frente, P05 BLOQUEADO), login legado da tabela `usuarios` e criação do
primeiro administrador (a interface nova só usa o Supabase Auth), Modo
Demonstração e o corte do Streamlit (P07: exige GO/NO-GO novo).

## Regras de toda fatia

- O domínio continua em `src/` e é o MESMO do Streamlit; a API só adapta.
  Módulo que puxa o Streamlit ganha `from .streamlit_opcional import st`.
- Toda leitura e escrita com o JWT do usuário; o RLS decide. Escrita com
  `If-Match` (trava otimista) e, quando cria, `Idempotency-Key`.
- Tarefa longa (IA, coleta, exportação) vai para o worker (Celery/Redis),
  com acompanhamento pela tela.
- Tela nova nasce do design system (`@/design-system`), sem valor solto.
- Prova de unidade na API e no web; E2E na pilha real quando a fatia tem
  fluxo de usuário.
