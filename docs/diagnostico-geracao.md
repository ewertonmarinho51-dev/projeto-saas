# Diagnóstico e correção do motor de geração de documentos

Data: 2026-07-12 · Base de comparação: documentos aprovados manualmente
pela Prefeitura Municipal de Paragominas × documentos gerados pelo sistema.

## 1. Diagnóstico do fluxo (auditoria da API)

Fluxo real: `ui/steps.py` (botão "Gerar com IA") → `llm.gerar_documento`
(backend/servidor Streamlit — a chave NUNCA vai ao navegador) →
`prompts.montar_prompt` (+ RAG) → OpenAI (principal) → Gemini (fallback
avisado) → preview editável → `export.py` (DOCX/PDF).

| Item auditado | Situação encontrada | Situação após correção |
|---|---|---|
| Carga da chave | painel admin > sidebar > secrets.toml > env (`llm._ler_chave`) | igual + origem exibida no admin |
| Chamada no backend | sim (servidor) | sim |
| Modelo efetivo | `gpt-5-mini` (+fallbacks 4o-mini/4o/4.1-mini) | igual, registrado por geração |
| Limite de saída | OpenAI 16384 / Gemini 8192 | OpenAI 16384 / **Gemini 16384** |
| Truncamento | resposta vazia tratada; sem log | vazio → troca de modelo; tudo logado |
| Fallback estático | Modo Demonstração (toggle EXPLÍCITO do usuário) | igual + registrado como `fallback=True` |
| Erros ocultos | mensagem amigável + detalhe técnico em expander | igual + registro persistente na sessão |
| Continua gerando se a API falha? | NÃO (erro exibido, nada gerado) | idem |
| Registros técnicos | **não existiam** | `llm.registrar_geracao`: data/hora, processo, documento, motor, modelo, duração, tokens in/out, request-id, status, erro sanitizado, flag de fallback — no log do servidor e no expander "Registro técnico de geração" da tela final. Sem chave nem conteúdo de documento nos logs. |

Comprovação de chamada real: o registro técnico grava `request_id` e
tokens devolvidos pela API — impossíveis de existir sem chamada real.
(Deste ambiente de desenvolvimento não há egress para api.openai.com;
a comprovação ao vivo é feita na implantação: Admin → Testar OpenAI e o
registro da primeira geração.)

## 2. Causa da geração resumida (comprovada por medição)

| Documento | Manual (aprovado) | Gerado (antes) | Fatores |
|---|---|---|---|
| DFD | 12 pág · 4.804 palavras · 9 cláusulas · itens 1.1/1.1.1 | 3 pág · 750 palavras · 7 cláusulas genéricas · sem subitens | (a) estrutura do prompt divergia do padrão da casa; (b) instrução "objetiva e enxuta"; (c) `reasoning_effort=minimal`; (d) sem metas de profundidade |
| ETP | 32 pág · 12.541 palavras · 18 cláusulas | 8 pág · 2.470 palavras | idem |
| TR | 24 pág · 11.412 palavras · 17 cláusulas | 9 pág · 3.003 palavras | idem |

Correções: perfis de cláusula (`src/perfis.py`) extraídos dos documentos
manuais com metas mín/média/máx de blocos e complexidade por cláusula,
injetados no prompt; regra anti-enchimento; `reasoning_effort=low`;
Gemini 16384 tokens.

## 3. Causa da quebra de formatação (comprovada por inspeção dos PDFs)

- Manuais: **Times 12**, texto justificado, margens regulares.
- Gerados (antes): **Helvetica 11** (fpdf2 desenhando direto), texto
  ultrapassando a margem direita (x máx > largura da página), títulos
  soltos, sem 1,5/6pt, sem estilo de cláusula.

Correção (arquitetura em camadas): conteúdo (IA, Markdown) → montagem
DOCX **com estilos centralizados** → conversão DOCX→PDF via LibreOffice →
validação. DOCX e PDF passam a ter o MESMO conteúdo e formatação.

## 4. Estilos DOCX implementados (`export.py`)

`GovDocs Corpo` (Times New Roman 12, 1,5 linhas, 6 pt após, justificado,
controle de órfãs/viúvas) · `GovDocs Titulo` (14 negrito centrado) ·
`GovDocs Clausula` (12 negrito, `keep_with_next` — título nunca separa do
1º parágrafo) · `GovDocs Item 1/2/3` (recuo 0,75/1,5/2,25 cm conforme
profundidade 1.1./1.1.1./1.1.1.1.) · `GovDocs Nota` (10) ·
`GovDocs Assinatura` (centrado, não divide entre páginas) · tabelas:
`Table Grid`, cabeçalho em negrito **repetido a cada página**
(`tblHeader`), linha indivisível (`cantSplit`), fonte 10. Página A4,
margens 2,5/2,5/2,0/2,0 cm. Cabeçalho/rodapé/logos: sistema de identidade
visual por imagem já existente (inalterado).

## 5. Validação automática (`src/validacao.py`)

Bloqueiam a emissão (download desabilitado até resolver na revisão):
`[PREENCHER…]`, `[[TABELA_ITENS]]`, "placeholder", menção a
formulário‑matriz/prompt/IA/base interna. Avisos: numeração duplicada ou
com salto, título sem conteúdo, tabela sem cabeçalho, cláusula
obrigatória ausente (vs. perfil), documento raso (< metade do piso de
palavras do documento manual). A tela final lista cada pendência com o
trecho e leva ao documento para correção.

## 6. Fontes de informação (prioridade aplicada nos prompts)

1º legislação/regulamentos/manuais da base de conhecimento → 2º processo
atual (memorando/ofício, formulário, planilha) → 3º processos anteriores
**somente como padrão de forma/estrutura** — proibido transportar
qualquer dado material. Informação ausente → `[PREENCHER]` **na revisão**
(o documento final não sai com o marcador — validação bloqueia).

## 7. Arquivos alterados

`src/perfis.py` (novo) · `src/validacao.py` (novo) · `src/prompts.py` ·
`src/llm.py` · `src/export.py` · `src/ui/steps.py` ·
`tests/test_validacao.py` (novo) · `tests/test_export_estilos.py` (novo)
· `tests/test_prompts.py` · `tests/test_llm.py` · `tests/test_app.py` ·
`docs/diagnostico-geracao.md` (este arquivo). **111 testes automatizados.**

## 8. Configuração / como testar localmente

1. `pip install -r requirements.txt` e **LibreOffice Writer** instalado
   (`packages.txt` já pede `libreoffice` no Streamlit Cloud; local:
   `apt install libreoffice-writer`). Sem ele o PDF cai para o
   renderizador fpdf2 (fonte Times nativa) — o motor ativo aparece no
   expander "Registro técnico" da tela final.
2. Chaves em `.streamlit/secrets.toml` (OPENAI_API_KEY, GOOGLE_API_KEY)
   ou Admin → Chaves de IA (prioridade máxima; origem exibida na tela).
3. `python -m pytest -q` (roda offline, 111 testes).
4. `streamlit run app.py` → gerar DFD→ETP→TR→Edital → tela final mostra
   validação, registro técnico e downloads (bloqueados se houver pendência).

## 9. Riscos e limitações remanescentes

- **Fonte**: no servidor Linux a conversão substitui Times New Roman por
  Liberation Serif (metricamente idêntica — mesmas quebras/medidas); o
  DOCX declara Times New Roman e abre com ela no Word/Windows. Instalar
  `fonts-liberation` garante a substituta correta.
- **Edital**: sem documento manual de referência no acervo — estrutura
  atual mantida (arts. 25/82-86). Enviar um edital aprovado para calibrar
  o perfil.
- **Mapa de Riscos**: hoje é cláusula do ETP (Análise de Riscos). Emitir
  como documento próprio = etapa nova do wizard (próximo incremento).
- **Geração cláusula a cláusula** (regenerar/bloquear cláusula
  individual, fonte por informação, diff de versões): arquitetura JSON
  por cláusula planejada como evolução — a base (perfis + validação +
  montagem estruturada) já está pronta para recebê-la.
- Validação de "resíduo de outro processo" é heurística (menções à
  mecânica interna); conferência semântica fina permanece na revisão
  humana, que continua obrigatória.
