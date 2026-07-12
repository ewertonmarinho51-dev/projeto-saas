# Auditoria e matriz de compatibilidade — pacotes v2 (arquitetura) e v1 (multi-município)

Data: 2026-07-12 · Escopo: repositório real (`projeto-saas`) × propostas dos
pacotes `pacote_arquitetura_saas_licitacoes_v2` e
`pacote_evolucao_multi_municipio_v1`.

## 1. Diagnóstico do repositório (stack real)

| Dimensão | Implementação atual |
|---|---|
| Arquitetura | Monólito Streamlit (app.py + src/), stateless por sessão; sem filas/workers |
| Autenticação | Própria: `src/auth.py`, PBKDF2-SHA256 200k, papéis `admin`/`usuario`, sessão via `st.session_state` |
| Banco | Supabase (Postgres gerenciado) via SDK; migrações SQL versionadas em `supabase/migrations/`; sem ORM |
| Entidades | `usuarios`, `processos` (dados/documentos/aprovados jsonb, `usuario_id`), `config_app` (chaves IA), `config_orgaos` (identidade visual por órgão), `documentos_referencia`+`chunks_referencia` (RAG pgvector) |
| Motor de geração | `llm.py` (OpenAI principal + fallbacks de modelo + Gemini; registro técnico com tokens/req-id), `prompts.py` + `perfis.py` (estrutura/profundidade das cláusulas dos docs aprovados), `validacao.py` (bloqueio de pendências), `export.py` (DOCX estilizado → LibreOffice → PDF) |
| RAG | Global (sem tenant), categorias lei/acórdão/entendimento/processo_anterior/modelo |
| Identidade visual | `config_orgaos`: imagem (cabeçalho/rodapé/marca) capturada de documento-modelo OU texto; aplicada na exportação |
| Assinaturas | Texto no corpo do documento (campo `responsavel` no formulário) — sem entidade Pessoa |
| Frontend | Wizard de 6 passos + páginas admin (usuários, chaves, identidade) e Base de Conhecimento |
| CI/Deploy | GitHub Actions (pytest, 112 testes); Streamlit Community Cloud (packages.txt: libreoffice) |
| Multi-tenant hoje | NÃO — tenant único implícito (Paragominas); RLS liberado para `anon` |

## 2. Matriz de compatibilidade

Legenda de decisão: ✅ já implementado · 🔄 compatível/reutilizável ·
🛠 compatível com adaptação · ♻️ incompatível mas objetivo aproveitável ·
⏸ desnecessário no momento · 🕐 fase posterior.

| Capacidade proposta | Implementação atual | Lacuna | Reutilizar/Adaptar/Criar | Arquivos | Migration | Risco | Decisão |
|---|---|---|---|---|---|---|---|
| **v2: motor 1 chamada/documento + contexto do processo** | `llm.gerar_documento` (1 chamada/doc, memorando+formulário+doc anterior+RAG) | — | reutilizar | llm.py, prompts.py | não | baixo | ✅ |
| **v2: perfis documentais** | `perfis.py` (DFD 9/ETP 18/TR 17 cláusulas, metas, complexidade) | catálogo por tenant | adaptar (chave por tenant depois) | perfis.py | não | baixo | ✅→🛠 |
| **v2: validações pré-emissão** | `validacao.py` (bloqueios+avisos) | validação visual do PDF (pág. em branco/corte) | adaptar | validacao.py | não | baixo | ✅→🛠 |
| **v2: auditoria de geração** | `llm.registrar_geracao` (sessão+log) | persistir em tabela por processo | adaptar | llm.py, db.py | `geracoes` (nova) | baixo | 🛠 Fase 1 |
| **v2: JSON canônico por cláusula + patches** | saída Markdown validada | schema JSON, regeneração por cláusula, diff | criar sobre perfis+validacao | novo módulo | não | médio | 🕐 Fase 3 |
| **v2: renderização determinística** | DOCX estilos → LibreOffice → PDF | blocos LOCKED (depende do catálogo) | reutilizar+adaptar | export.py | não | baixo | ✅→🛠 |
| **mm: `tenant_id` nas entidades** | inexistente (tenant único) | coluna+default+RLS | criar (expand/contract) | migrations, db.py | 0006: `tenants` + `tenant_id` DEFAULT tenant-Paragominas em processos/config_*/documentos_referencia/usuarios; backfill | médio | 🛠 **Fase 1** |
| **mm: secretarias** | `config_orgaos.orgao` (texto) ≈ proto-secretaria | tabela própria + vínculo do usuário | adaptar `config_orgaos`→`secretarias` (manter colunas de branding) | db.py, admin.py | 0007 | médio | 🛠 Fase 2 |
| **mm: contexto derivado da sessão (nunca do form)** | `usuario_logado()` em sessão | tenant/secretaria no vínculo do usuário | adaptar auth | auth.py, state.py | usa 0006/0007 | médio | 🛠 Fase 2 |
| **mm: herança visual (secretaria herda/sobrescreve município)** | `config_orgaos` com flag `padrao` = base pronta | resolver hierárquico com origem do valor | adaptar (resolver + shadow mode) | branding.py, export.py | não | baixo | 🛠 Fase 2 |
| **mm: templates versionados com blocos LOCKED/AI/SIGNATURE** | perfis (estrutura) + estilos (forma) | entidade template+versão imutável | criar, reutilizando perfis como semente | novo módulo + tabela | 0008 | alto | 🕐 Fase 3 |
| **mm: catálogo de cláusulas versionado (hash, vigência, aprovação)** | textos padrão vivem nos docs aprovados (RAG) | tabela `clausulas`+`clausula_versoes`; migrar textos p/ revisão (NUNCA inventar conteúdo) | criar | novo módulo + tabelas | 0009 | alto | 🕐 Fase 3 |
| **mm: motor de políticas (DSL declarativa + simulador)** | condicional única no código (SRP em perfis/prompts) | DSL JSON validada, prioridade, conflito bloqueia | criar; SRP vira 1ª política | novo módulo | 0010 | alto | 🕐 Fase 4 |
| **mm: pessoas/vínculos/papéis/elegibilidade** | `usuarios` (login) + `responsavel` texto | Pessoa institucional, vínculo c/ vigência, papéis documentais | criar; `usuarios` ganha FK pessoa | novo módulo + tabelas | 0011 | alto | 🕐 Fase 4 |
| **mm: slots de assinatura por papel (secretário ≠ elaborador)** | assinatura como texto no corpo | slots no template + filtro por elegibilidade + snapshot | criar (depende de pessoas+templates) | export.py, novo módulo | usa 0008/0011 | alto | 🕐 Fase 4 |
| **mm: snapshot de contexto no documento emitido** | `processos.dados/documentos` já congelam conteúdo | congelar branding/versões/assinantes resolvidos | adaptar (campo `snapshot` jsonb) | state.py, db.py | 0006 (coluna) | baixo | 🛠 Fase 1 |
| **mm: RAG/storage/cache isolados por tenant** | RAG global; sem storage de arquivos; cache st.cache | `tenant_id` em documentos_referencia + filtro nas buscas RPC | adaptar | rag.py, migração RPC | 0006 | médio | 🛠 Fase 2 |
| **mm: painel proprietário (municípios/secretarias/flags/auditoria)** | Admin atual (usuários/chaves/identidade) | novas abas por fase | adaptar incrementalmente | ui/admin.py | — | médio | 🛠 contínuo |
| **mm: jornada do servidor enxuta** | wizard atual já esconde prompt/IA/técnica | seleção automática de secretaria pelo vínculo | adaptar | ui/steps.py | — | baixo | ✅→🛠 |
| **mm: filas/workers, object storage, canário, IA-ops (PR bot)** | inexistente | — | — | — | — | — | ⏸ escala atual (Streamlit Cloud, 1 município) não justifica; reavaliar no 2º tenant |
| **mm: URLs temporárias de arquivo** | downloads gerados na sessão (não persistidos) | só se houver storage | — | — | — | — | ⏸ junto com storage |
| **mm: microserviços** | monólito modular | — | — | — | — | — | ⏸ descartado pelo próprio pacote |

## 3. Plano incremental adaptado à stack real (com flags e rollback)

Cada fase = migração expand/contract (nada é dropado na mesma release),
feature flag em `config_app` (`flag_*`, default OFF), testes negativos de
acesso cruzado, e rollback = desligar a flag (colunas novas ficam inertes).

- **Fase 1 — Fundação de tenant (sem mudança visível).** Migração 0006:
  tabela `tenants` (Paragominas como tenant padrão), coluna `tenant_id`
  com DEFAULT em `processos`, `usuarios`, `config_app`, `config_orgaos`,
  `documentos_referencia`; coluna `snapshot` em `processos`; tabela
  `geracoes` (persistência do registro técnico). Backfill automático no
  próprio SQL. `db.py` passa a gravar/filtrar `tenant_id` do contexto da
  sessão (hoje: constante do tenant padrão). Testes: isolamento (consulta
  de tenant B não vê dados do A), flags OFF = comportamento idêntico.
- **Fase 2 — Secretarias + herança visual + RAG por tenant.**
  `config_orgaos`→`secretarias` (rename expand/contract), vínculo
  usuário↔secretaria, resolvedor de branding hierárquico (documento >
  secretaria > município) rodando em *shadow mode* (loga a decisão, aplica
  o comportamento antigo) antes do corte; filtro de tenant nas RPCs do RAG.
- **Fase 3 — Templates versionados + catálogo de cláusulas.** Entidades
  versionadas e imutáveis; conteúdo de cláusula SÓ migrado de documentos
  aprovados (estado "em revisão" → publicação manual); blocos
  FIXED_LOCKED inseridos deterministicamente pelo compositor (a IA nunca
  recebe esses trechos para reescrever); regeneração por cláusula.
- **Fase 4 — Políticas + pessoas + assinaturas.** DSL declarativa em JSON
  (validada por schema; conflito sem prioridade ⇒ bloqueia publicação),
  simulador no painel; Pessoa/Vínculo/Papel com vigência; slots de
  assinatura por elegibilidade (secretário fora do slot de elaborador);
  snapshot congela nome/cargo/papel no documento emitido.
- **Fase 5 — 2º tenant piloto** com checklist de isolamento completo.

## 4. Decisões que precisam do proprietário antes da Fase 2+

1. **Supabase Auth vs auth própria**: para multi-tenant real com RLS por
   tenant, migrar para Supabase Auth (RLS `auth.uid()`) é o caminho
   robusto; a auth própria atual exige RLS via chave service-role no
   backend. Recomendação: Supabase Auth na Fase 2.
2. **Catálogo de cláusulas**: enviar os textos aprovados oficiais (por
   família: obrigações, sanções, pagamento…) — o sistema não inventa
   conteúdo jurídico.
3. **Edital**: continua sem modelo manual de referência.

## 5. Estado desta entrega

Implementado agora (além da auditoria): correção do crash de produção no
fallback de tabela do fpdf2 (linha mais alta que a página → degrade
controlado de fonte e, em último caso, parágrafos). A Fase 1 (migração
0006 + tenant padrão + persistência do registro de gerações) é o próximo
incremento de código, após aplicação do patch atual em produção e
confirmação do baseline verde.
