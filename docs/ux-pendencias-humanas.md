# UX de intervenção humana / dados ausentes

Branch `ux-pendencias-humanas` (a partir de `main` `80d2d53`, já com P0 e
P1). **Nenhum PR aberto, nenhum merge.**

Defeito reportado em produção: a tela final pedia ajuda humana exibindo

```
informação pendente (documento DFD)
informação pendente (documento ETP)
informação pendente (documento TR)
informação pendente (documento EDITAL)
```

O servidor não tinha como saber o que responder. Critério de aceite
adotado: **se o sistema pede ajuda humana, o usuário nunca pode ter que
adivinhar o que o sistema quer saber.**

---

## A. Causa-raiz (três causas convergentes, nenhuma nova)

| # | Causa | Onde |
|---|---|---|
| 1 | O nome do campo só existia se o marcador trouxesse descrição. Marcador "seco" (`[PREENCHER]`) caía no literal `"informação pendente"` | `achados._campos_requeridos` — `m.group(1).strip() or "informação pendente"` |
| 2 | O próprio sistema ensinava o marcador seco | `prompts.py` ("Onde faltar dado, use `[PREENCHER]`"), `rag.montar_bloco_referencias` (mesma frase) e `llm._gerar_demo` |
| 3 | A extração varria o **documento inteiro**, não a evidência do achado; e o validador emitia **um único achado agregado** ("N ocorrência(s)") para todos os marcadores — nenhuma pendência era endereçável individualmente | `validacao._validar_bloqueantes`, `achados.estruturar` |

Efeito colateral da causa 3, encontrado durante a correção: findings de
`MISSING_REQUIRED_DATA` **sem marcador** (matrícula improvisada, CNPJ
inválido) nunca recebiam `camposRequeridos`. O estado ia para
`WAITING_REQUIRED_DATA` e a tela abria um **formulário vazio**.

## B. Arquitetura reutilizada (nenhum mecanismo paralelo)

Tudo entrou nos módulos que já exerciam a função:

- `validacao.py` — já era o dono do padrão `[PREENCHER]`. Ganhou
  `campos_pendentes()` (identificação determinística do campo) e
  `pendencia_de_valor()` (dado improvisado). Um achado **por** pendência.
- `achados.py` — findings estruturados, `blockingReason`,
  `camposRequeridos` (contrato preservado: lista de strings, consumida
  pelo `corretor.requiredFields`). Ganhou `pendencias` ao lado.
- `ciclo.py` — `campos_requeridos` já existia; ganhou deduplicação e
  `decisoes_requeridas`.
- `ui/revisao.py` — as telas `WAITING_REQUIRED_DATA` e
  `BLOCKED_BY_CONFLICT` já existiam; foram redesenhadas.

Nenhum arquivo novo em `src/`. Nenhuma flag nova. Nenhuma alteração em
RAG/V2/embeddings/HNSW/RPC vetorial, no fluxo DFD → ETP → TR → Edital
nem no motor de patches.

## C. Como o nome do campo é obtido (determinístico, sem IA)

Ordem de precisão, registrada em `pendencia["origem"]`:

| origem | regra | exemplo |
|---|---|---|
| `marcador` | a descrição do próprio marcador | `[PREENCHER: prazo de vigência]` → *prazo de vigência* |
| `tabela` | cabeçalho da coluna + primeira célula da linha | `\| Atraso \| [PREENCHER] \|` → *Probabilidade — Atraso na entrega* |
| `rotulo` | rótulo que antecede o marcador na linha, sem numeração de cláusula | `3.2. Prazo de vigência: [PREENCHER]` → *Prazo de vigência* |
| `clausula` | título da cláusula mais próxima | `## 4. ENCERRAMENTO` + `[PREENCHER]` → *conteúdo de «4. ENCERRAMENTO»* |
| `trecho` | último recurso: cita o trecho | `[PREENCHER] do contrato` → *informação pendente em "___ do contrato"* |
| `valor_improvisado` | campo declarado pela regra | `matrícula: 15` → *matrícula do agente responsável* |

Siglas permanecem em caixa alta (`PCA`, não `Pca`). O rótulo genérico
seco **nunca** é exibido: mesmo no último recurso a pergunta carrega o
trecho.

## D. Deduplicação

Uma pergunta por dado, com `alvos` (documento + marcador exato +
ocorrência) para aplicar a resposta em todos os pontos:

- **entre documentos** — o prazo de vigência do DFD e o do ETP são o
  mesmo fato do processo: uma pergunta, resposta aplicada aos dois;
- **exceção posicional** — quando o nome veio da posição (coluna de
  tabela, título de cláusula, trecho) ou o alvo é um valor improvisado, o
  mesmo rótulo se repete em pontos que pedem valores **diferentes** (a
  "Ação preventiva" do risco A não é a do risco B; a matrícula da Ana não
  é a do Bruno). Aí a chave inclui o contexto — a resposta de um ponto
  nunca vaza para os demais.

## E. Dado ausente × decisão discricionária

| | `MISSING_REQUIRED_DATA` | `DISCRETIONARY_DECISION` |
|---|---|---|
| natureza | falta informação do processo | falta uma escolha do revisor |
| tela | campo de texto, com cláusula e trecho | card com o que se espera + botão **"Ir para o TR"** |
| aplicação | substituição por código (`DOCUMENTOS[doc]["etapa"]` + `state.ir_para`) | nenhuma — o revisor edita o documento |

Decisão discricionária nunca vira caixa de texto: o sistema não tem como
receber a resposta como dado.

## F. Aplicação da resposta (segurança preservada)

- substituição **por código**, nunca por IA, nunca abrindo o documento
  para edição livre;
- alvo cirúrgico: marcador exato + número da ocorrência. Marcadores secos
  são idênticos entre si — sem a ocorrência, responder uma linha
  sobrescreveria as outras;
- **ordem de aplicação**: da última ocorrência para a primeira
  (`aplicar_respostas`). Aplicar na ordem do formulário deslocava as
  ocorrências seguintes e a resposta 2 caía na lacuna errada — bug real,
  encontrado no fim a fim das 4 minutas e coberto por teste;
- dado improvisado usa `molde` (`"matrícula: {valor}"`), preservando o
  rótulo em volta;
- campo em branco não altera nada: **dado ausente não é inventado**,
  `[PREENCHER]` continua bloqueando a emissão e a intervenção humana
  continua obrigatória.

## G. Antes × depois (texto real da tela)

Fonte: as 4 minutas de `llm._gerar_demo` (mesma origem dos marcadores
secos do defeito), com `orgao`/`responsavel` vazios.

**Antes — 28 campos, 19 genéricos:**

```
• informação pendente (documento DFD)      • informação pendente (documento ETP)
• informação pendente (documento DFD)      • informação pendente (documento ETP)
• informação pendente (documento DFD)      • pesquisa de mercado (documento ETP)
• PCA (documento DFD)                      • análise (documento ETP)
• prazo (documento DFD)                    • informação pendente (documento ETP)  ×4
• informação pendente (documento DFD)      • conclusão (documento ETP)
• informação pendente (documento TR) ×4    • informação pendente (documento EDITAL) ×3
• critérios de medição… (documento TR)     • condições / critério / assinatura (EDITAL)
```

**Depois — 19 campos, 0 genéricos:**

```
• Órgão requisitante (DFD, ETP, TR, Edital)
     Cláusula 1. Identificação · "- Órgão requisitante: [PREENCHER]" ·
     a mesma resposta completa todos os documentos acima
• Responsável (DFD, ETP, TR, Edital)
• conteúdo de «3. Justificativa da Necessidade» (DFD, ETP, TR, Edital)
• PCA (DFD)                       Cláusula 4. Alinhamento ao Planejamento
• prazo (DFD)                     Cláusula 6. Previsão e Prioridade
• Local e data (DFD)              Cláusula 7. Encaminhamento
• conteúdo de «4. Requisitos da Contratação (art. 18, §1º, III)» (ETP)
• pesquisa de mercado (ETP)       Cláusula 5. Levantamento de Mercado
• análise (ETP)                   Cláusula 6. Justificativa do Parcelamento
• Probabilidade — Atraso na entrega (ETP)   Cláusula 7. Matriz de Riscos
• Impacto — Atraso na entrega (ETP)
• Mitigação — Atraso na entrega (ETP)
• Responsável — Atraso na entrega (ETP)
• conclusão (ETP)                 Cláusula 8. Declaração de Viabilidade
• conteúdo de «4. Requisitos e Especificações (art. 6º, XXIII, 'd')» (TR)
• critérios de medição e recebimento (TR)
• condições — arts. 14 e 62 a 70 (Edital)
• critério — art. 33 (Edital)
• condições de assinatura (Edital)

Decisões que dependem de você
  [DFD · etapa 1] documento raso: 218 palavras…      [Ir para o DFD]
  [ETP · etapa 2] documento raso: 129 palavras…      [Ir para o ETP]
  [TR  · etapa 3] documento raso: 106 palavras…      [Ir para o TR]
```

De 28 perguntas para 19 (deduplicação entre documentos) e de 19 rótulos
genéricos para **zero**. Respondendo as 19, restam **0 marcadores** nos
4 documentos e **0 perguntas** na reauditoria.

## H. Testes

`tests/test_pendencias_humanas.py` (novo, 23 casos) cobre: nome do campo
nas seis origens; regressão da tela reportada (nenhum rótulo genérico);
um achado por marcador; alvo exato no finding; dedup entre documentos;
não-dedup de homônimos posicionais; dado ausente sem marcador
(matrícula/CNPJ) com aplicação via molde; decisão discricionária como
card com etapa; ordem das substituições; resposta em branco; e o fim a
fim "perguntar → responder → revalidar → deixar de bloquear".

`tests/test_revisao_ui.py` ganhou o teste de tela (AppTest) que falha se
qualquer rótulo contiver `informação pendente` ou `documento DFD`.

Testes ajustados ao novo contrato: `test_ciclo` (payload enriquecido de
`campos_requeridos`) e `test_rag` (marcador ensinado com descrição).

```
557 passed, 1 failed
```

A única falha é `test_export_estilos::test_pdf_via_libreoffice_quando_disponivel`
— **pré-existente e sem relação** com esta mudança (fonte Helvetica na
conversão do LibreOffice deste contêiner); confirmada em `main` limpo
antes de qualquer alteração.
