# Validação Pré-Merge — Auditoria P0 (`auditoria-correcao-p0`)

**Data:** 09/08/2026. **Ambiente:** container de validação com o pipeline
completo (geração → injeção de tabela → validação → export DOCX →
LibreOffice → PDF), planilha REAL reconstruída dos documentos originais
(190 itens recuperados da extração do ETP; a extração de PDF é lossy —
191 códigos na tabela original renderizada; 1 item sem linha de valores
descartado sem inventar números). **Limitação declarada:** o ambiente
não possui chaves de API (OpenAI/Gemini) nem Supabase — a geração por IA
real não pôde ser executada aqui; o fluxo foi exercitado (a) pelo
caminho `gerar_documento` do app em Modo Demonstração, (b) por replay da
saída defeituosa LITERAL do modelo original contra `main` e contra a
branch, e (c) por saída correta esperada contra a branch.

## A. Resultado end-to-end (mesma contratação, DFD→ETP→TR→Edital)

Replay da saída defeituosa (réplica literal dos defeitos originais) no
pipeline de cada versão:

| Documento | Antes (main) | Depois (branch) | Status |
|---|---|---|---|
| DFD | tabela SEM cabeçalho real; **item 572704 = 115× no PDF; 115 páginas**; 2 tabelas (marca duplicada); URL/cargo/999999 passam; 1 bloqueio | 1 tabela com cabeçalho real; **572704 = 1×; 40 páginas**; 3 bloqueios (URL crua, cargo inválido, etiqueta) | ✔ corrigido |
| ETP | "Representante: alto" passa; art. 98 p/ pagamento passa | bloqueio de cargo inválido; avisos de art. 98 e repactuação | ✔ corrigido |
| TR | matrícula 999999 passa; art. 98 passa | matrícula → aviso (dado pode ser real; vai à revisão); art. 98/repactuação → avisos | ✔ conforme desenho |
| Edital | tabela sem cabeçalho; **572704 = 50× em 50 páginas**; art. 109 passa | 1 tabela; **572704 = 1×; 39 páginas**; **bloqueio: pregão × art. 109** | ✔ corrigido |

Com saída CORRETA do modelo (branch): 4 documentos com exatamente
1 cabeçalho de tabela, 190 códigos únicos, 572704 = 1× no PDF, 39–40
páginas, `VALOR GLOBAL` presente e igual à soma exata dos itens
(R$ 7.361.978,42 para os 190 itens reconstruídos), zero resíduos; único
bloqueio: `[PREENCHER]` do DFD (comportamento desejado — revisão humana).

Fluxo `gerar_documento` real (Modo Demonstração): executa ponta a ponta;
no DFD o esqueleto demo embute a amostra do formulário e o NOVO validador
bloqueia por "tabela de itens duplicada" — comportamento correto do
validador sobre uma peculiaridade exclusiva do modo demo (esqueleto
offline, sempre inapto a emissão por [PREENCHER]).

## B. Defeitos P0 — reproduzidos após a correção?

| Defeito | Reproduzido? | Evidência |
|---|---|---|
| 1º item repetido em toda página | NÃO | 572704: 115×→1× (DFD), 50×→1× (Edital) |
| Tabela duplicada (marca 2×) | NÃO | 2 tabelas → 1; cabeçalho `\| Código \|` = 1 por doc |
| 1 item por página | NÃO | 115/103 págs → 40; linha longa divide entre páginas |
| Valor global | preservado | soma exibida = soma exata dos itens de entrada |
| `999999` | detectado (aviso) | vai à revisão; não bloqueia por poder ser dado real |
| `matrícula: 15` / repr. `15` / `alto` | NÃO emite | bloqueio "função/cargo com valor inválido" |
| URL de loja na prosa | NÃO emite | bloqueio "URL crua na prosa" (allowlist gov.br) |
| Placeholders internos | NÃO emite | `[PREENCHER]`/`[[TABELA_ITENS]]` seguem bloqueando |
| Dados de outra contratação | NÃO | teste de 2 contratações consecutivas (seção D) |

## C. RAG jurídico

No ambiente de validação a base de conhecimento está indisponível (sem
Supabase/chaves): as buscas retornam vazio e nenhum chunk pôde ser
inspecionado — a coluna "chunk recuperado" abaixo reflete isso com
honestidade. A verificação de pertinência foi DETERMINÍSTICA
(`validacao._validar_fundamentos_legais`):

| Afirmação (replay) | Artigo utilizado | Chunk recuperado | Fonte | Correto? |
|---|---|---|---|---|
| "Modalidade: Pregão Eletrônico, na forma do art. 109" | art. 109 | nenhum (base indisponível) | memória do LLM | ✗ → **bloqueia**; correto: arts. 28, I, e 29 |
| "vigência da Ata… (art. 82)" | art. 82 | nenhum | memória do LLM | ✗ → aviso; correto: art. 84 |
| "pagamento antecipado… (art. 98 e 103)" | art. 98 | nenhum | memória do LLM | ✗ → aviso; correto: arts. 141–146 (art. 98 = limite da garantia) |
| "repactuação de preços" (bens/materiais) | — | nenhum | memória do LLM | ✗ → aviso; correto: reajuste, art. 92, §3º |
| "arts. 28, I, e 29" / "art. 84" / "arts. 141 a 146" / "arts. 155 e 156" | corretos | nenhum | mapa canônico | ✓ passam sem achado |

**O mapa canônico NÃO é considerado a solução do RAG** — é barreira
auxiliar. Plano para o RAG EXISTENTE (P1, sem criar outro RAG):

1. `rag.buscar_referencias` já retorna `similaridade`, `titulo` e
   `categoria` (RPCs das migrações 0003/0007) — hoje descartados por
   `montar_bloco_referencias`.
2. Aprimoramento no próprio `rag.py`: (a) consultas POR TEMA da cláusula
   (vigência, pagamento, sanções…) além da consulta única
   objeto+justificativa; (b) piso de similaridade; (c) instrução no bloco
   de referências: "cite número de artigo SOMENTE se constar de um trecho
   recuperado ou do mapa canônico; senão cite a lei genericamente";
   (d) o fluxo afirmação→consulta→recuperação→confirmação→redação→
   registro usa `montar_bloco_referencias` + `registrar_geracao`
   existentes.
3. Verificação determinística pós-geração (já implementada) permanece
   como terceira camada.

## D. Estado (duas contratações consecutivas)

Contratação A (expediente, "agosto de 2026", Luan Jardel) → geração →
caches populados (`_ciclo_resultado`, `_fatos_cache`,
`_familia_escolha_dfd`) → **Novo processo** → Contratação B
(medicamentos, "dezembro de 2027", Maria Souza):

- termos de A no documento de B: **NENHUM**;
- caches de A após o reinício: **NENHUM**;
- estado global preservado: `usuario`, `modo_demo` (e `tenant_id`,
  chaves de API — cobertos por teste);
- documento B contém somente dados de B: **sim**.

Auditoria da convenção `_` no repositório inteiro: 11 chaves `_*`
encontradas; `_modelo_chave`/`_modelo_img` são estado GLOBAL do admin
(preview de branding) — a limpeza genérica por prefixo foi SUBSTITUÍDA
por lista explícita (`state._CHAVES_DO_PROCESSO` +
`_PREFIXOS_DO_PROCESSO`), com teste garantindo que autenticação, tenant,
chaves de API e caches globais sobrevivem ao reinício.

## E. Suíte comparativa

- `main`: **366 passed / 1 failed**
- `auditoria-correcao-p0`: **395 passed / 1 failed**

A única falha é a MESMA em ambas (`test_export_estilos.py::
test_pdf_via_libreoffice_quando_disponivel` — o LibreOffice do container
substitui Times por Helvetica), comprovadamente pré-existente na `main`.
A branch adiciona 29 testes e nenhuma regressão.

## F. Campos exigidos pelos perfis sem fonte estruturada

| Campo do perfil | Classificação | Detalhe |
|---|---|---|
| Responsável pela demanda (nome/cargo) | **A** — existe e é usado | campo `responsavel` do formulário + fato canônico v5 |
| Data pretendida da contratação | **A** — existe e é usado | campo `prazo` + fato canônico |
| Matrícula do responsável | **C** | `usuarios` só tem nome/login/papel — sem matrícula; nenhuma outra fonte |
| Equipe de planejamento (membros/funções) | **C** | inexistente em banco/cadastros; `usuarios` não modela função no processo |
| Prioridade da demanda (grau) | **C** | sem campo e sem base para derivação determinística |
| Data de conclusão da fase preparatória | **C** | não derivável do `prazo` sem regra institucional |
| CNPJ do órgão | **C** | `tenants` tem slug/nome/uf; branding é texto livre — sem CNPJ estruturado |

Nenhum campo novo foi implementado (conforme instrução). Enquanto forem
C, o contrato vigente é: `[PREENCHER: …]` + resolução pontual na revisão
(`aplicar_dado_pontual`) — agora protegido pelos bloqueios de improviso.

## G. Recomendação

**APTO PARA PR.**

Justificativa: (1) as três causas-raiz mecânicas (injeção da tabela,
promoção do 1º item a cabeçalho, cantSplit) não se reproduzem nem sob o
replay literal da saída defeituosa original — com redução de 115→40
páginas e 115×→1× do primeiro item; (2) todos os vazamentos P0 agora
bloqueiam a emissão ou geram aviso rastreado no ciclo existente; (3) o
isolamento entre contratações foi comprovado e a limpeza usa lista
explícita que preserva o estado global; (4) suíte sem regressões vs
`main` (mesma única falha pré-existente). Ressalvas registradas, sem
impedir o merge: smoke test com IA real no Streamlit Cloud após o
deploy (não executável neste ambiente por ausência de chaves), e o
aprimoramento do RAG existente + trace (`geracoes.rag_trace` jsonb,
expand-only) permanecem como P1 — o mapa canônico é barreira auxiliar,
não a solução do grounding.
