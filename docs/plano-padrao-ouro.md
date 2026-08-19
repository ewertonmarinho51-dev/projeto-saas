# Plano para alcançar e superar o padrão ouro

Data: 19/08/2026. Base: `main` em `d160a80`, comparada com a branch
`correcao-padrao-ouro-documentos` (não mesclada).

## 1. O que foi executado — e o que não foi

**Executado.** Um processo real anonimizado (materiais de expediente,
**210 itens**, R$ 8.024.834,67) passou pelo pipeline determinístico da
`main`: planilha → cálculo → injeção da tabela → geração dos quatro
documentos → validação → exportação DOCX e PDF. Os artefatos ficaram
gravados e foram medidos um a um.

**NÃO executado: o caminho da IA.** Não há chave de OpenAI nem de
Gemini neste ambiente (há egress — a API responde 401 —, falta a
credencial). A prosa foi gerada em **Modo Demonstração**, que é uma
minuta-esqueleto offline e **não representa** o que a IA produz.

Consequência honesta: **a comparação de extensão e profundidade textual
com o padrão ouro continua sem medição minha.** O que este documento
mede é tudo o que não depende do modelo — tabela, estrutura, validação,
exportação — e é onde estão os defeitos que encontrei.

## 2. Como o sistema funciona

```
formulário → prompts.montar_prompt (+ perfis.py + RAG)
           → llm.gerar_documento  (OpenAI gpt-5-mini → Gemini fallback)
           → planilha.injetar_tabela   (substitui [[TABELA_ITENS]])
           → validacao.validar_todos   (bloqueios × avisos)
           → ciclo.executar_com_persistencia  (autocorreção por patches)
           → export: Markdown → DOCX com estilos → LibreOffice → PDF
```

Duas decisões de arquitetura que se mostraram acertadas na medição:

- **`perfis.py` já carrega o padrão ouro em números.** As metas foram
  extraídas dos documentos aprovados manualmente: DFD ~4.800 palavras e
  9 cláusulas, ETP ~12.500 e 18, TR ~11.400 e 17, com faixas de blocos
  por cláusula. O alvo certo já está no código; o que não sei é se a
  saída da IA o alcança.
- **A exportação está na arquitetura correta.** O motor efetivo é o
  **LibreOffice** (DOCX → PDF), não mais o fpdf2 que desenhava direto.
  O corpo sai em Times-Roman/Times-Bold; a única fonte sem serifa é a
  numeração de página no rodapé, que é assim de propósito.

## 3. Medição — `main`, caso de 210 itens

| aferição | resultado |
|---|---|
| itens na tabela | **210 / 210** |
| valor global recalculado | **R$ 8.024.834,67** — confere ao centavo |
| motor de PDF | LibreOffice |
| fonte do corpo | Times-Roman / Times-Bold |
| páginas por documento | 35–36 (≈150 do dossiê são tabela) |
| achados da validação | 57, sendo **16 bloqueantes** |

A integridade da planilha — que era o defeito mais grave do caso real
(tabela parcial de 53 códigos de 210 no edital) — **está resolvida na
`main`**. Conferi contra a fonte: 210 itens, nenhum perdido, total
exato.

> Correção de um erro meu no meio da apuração: cheguei a contar 204
> códigos e quase relatei perda de 6 itens. A regex é que exigia 5
> dígitos, e 6 códigos do caso têm 4 (`763`, `790`, `2219`, `2342`,
> `3810`, `7006`). A tabela estava certa; a medição é que estava errada.

## 4. Achados

### A. Instruções do prompt vazam para dentro do documento — nas DUAS branches

No DFD gerado, o corpo do documento contém:

```
IMPORTANTE: NÃO redija a lista de itens um a um — nem a partir desta amostra…
Amostra apenas ilustrativa dos primeiros itens (não a reproduza):
| Código | Descrição | Unidade | ...        ← tabela de amostra
… coloque a marca  EXATAMENTE UMA VEZ, SOZINHA em …
```

`_gerar_demo` cola `formatar_dados_formulario(dados)` no corpo, e essa
função produz **material de prompt** — texto endereçado ao modelo,
incluindo uma tabela de amostra. O resultado é um documento oficial que
instrui o leitor a não redigir a lista de itens.

Está na `main` **e na branch do padrão ouro**. Nenhum validador pega:
não há regra que reconheça linguagem de prompt no corpo.

### B. Tabela duplicada no DFD — resolvido na branch, não na `main`

Mesma origem: a amostra do prompt vira uma segunda tabela. Medi 2
cabeçalhos `| Código |` no DFD da `main` e 1 na branch. O validador da
`main` acusa ("tabela de itens duplicada"), mas acusar não é evitar.

### C. Texto fora da página

A folha A4 tem 595,3 pt de largura. Encontrei 4 trechos com borda
direita em **598,1 e 602,7 pt** — fora do papel, não apenas da margem.
São linhas de rótulo (`- Responsável…`, `- Prazo / D…`) que não quebram.
É o mesmo sintoma que o diagnóstico anterior atribuiu ao fpdf2, mas
agora com LibreOffice: **a causa é outra e continua aberta.**

### D. A docstring de `gerar_documento` descreve um defeito que não existe

Ela diz que "sem chave […] devolve uma minuta-esqueleto offline". O
código faz o **oposto e certo**: sem chave, levanta `ErroGeracaoIA`. O
Modo Demonstração é toggle explícito de administrador. Uma docstring
que promete fallback silencioso convida alguém a implementá-lo.

### E. O maior achado: o padrão ouro está pronto e fora da `main`

A branch `correcao-padrao-ouro-documentos` tem **4.363 linhas**, passa
**641/641** dos próprios testes, e não está mesclada. A `main` não tem:

| o que falta na `main` | por que importa |
|---|---|
| `versao_do_auditor()` | sem ela, um `APPROVED` de auditor obsoleto é reproduzido para sempre pela `idempotency_key`, e os validadores novos **nunca rodam** |
| `_validar_tabela_de_itens` | confere a tabela contra a fonte: contagem, códigos e total |
| `_validar_identificacoes` | pega matrícula `999999`, CNPJ de 15 dígitos, cargo preenchido com número |
| `_validar_fundamentos_legais` + `_natureza_do_objeto` | pega pregão fundado no art. 109, repactuação em aquisição de bens, vigência de ARP fora do art. 84 |
| `_validar_referencias_internas` | referências cruzadas quebradas |
| **ARP como documento próprio** | na `main` a Ata existe só como anexo dentro do edital, e não é exportada como arquivo |
| `TEMPLATE_EDITAL` / `TEMPLATE_ARP` | estrutura oficial completa |

Sondei a mesclagem: **um único arquivo conflita**, `src/ui/steps.py`,
porque o redesenho GovConnect o reescreveu. Todo o resto casa sozinho.

## 5. Plano

### Fase 1 — mesclar o que já existe (maior ganho, menor risco)

1. resolver o conflito em `src/ui/steps.py` — o redesenho manda no
   layout, a branch manda no fluxo de validação e no ARP;
2. rodar as duas suítes juntas (902 da `main` + 641 da branch);
3. reexecutar este mesmo caso de 210 itens e reconferir A, B e C.

**Entrega:** as sete lacunas da tabela acima deixam de existir.

### Fase 2 — fechar os três defeitos que sobrevivem à mesclagem

4. **separar prompt de conteúdo.** `formatar_dados_formulario` passa a
   ter duas saídas — uma para o modelo, outra para o documento — e
   `_gerar_demo` só pode usar a segunda. É a correção de A e B na raiz;
5. **validador de linguagem de prompt no corpo**: "não reproduza",
   "amostra ilustrativa", "EXATAMENTE UMA VEZ", `[[TABELA_ITENS]]`
   residual. Bloqueante — texto endereçado ao modelo em documento
   oficial é defeito grave;
6. **quebra de linha nos rótulos longos** e uma prova de exportação que
   reprove qualquer span com `x1 > largura da página`. Hoje a suíte
   confere fonte e rodapé, não geometria;
7. corrigir a docstring de `gerar_documento`.

### Fase 3 — medir o caminho da IA (o que ninguém mediu ainda)

8. configurar a chave num ambiente de ensaio e gerar os quatro
   documentos do mesmo caso;
9. medir contra `perfis.py`: palavras e cláusulas por documento;
10. **prova de regressão de profundidade** — falha se o DFD sair abaixo
    de ~4.800 palavras ou 9 cláusulas, o ETP abaixo de ~12.500 e 18, o
    TR abaixo de ~11.400 e 17. Sem isso, "está no padrão" é opinião.

### Fase 4 — superar o padrão ouro

O padrão ouro é um documento humano aprovado; superá-lo não é escrever
mais, é **garantir o que o humano não garante**:

11. **conferência aritmética total** — cada linha da tabela, o total, e
    a coerência com o valor declarado no texto, em todos os documentos;
12. **rastro de fundamentação por cláusula**: cada cláusula com base
    legal aponta o dispositivo, e o validador confere se ele existe e se
    cabe à natureza do objeto. O documento manual não tem isso;
13. **consistência entre documentos** — objeto, valor, quantidades e
    prazos idênticos em DFD, ETP, TR, Edital e ARP. É onde o processo
    manual mais falha, e é verificável por máquina;
14. **diferencial contra o caso aprovado**: rodar o mesmo processo e
    exigir zero dos 6 bloqueios que o caso real trazia.

## 6. Ordem sugerida

Fase 1 primeiro, e sozinha: ela transforma sete lacunas em zero sem
escrever código novo. Fase 2 na sequência, porque são três defeitos que
a mesclagem **não** resolve. Fase 3 depende de uma chave de API — é o
único item que não posso destravar daqui. Fase 4 é o que muda a
pergunta de "chegamos ao padrão?" para "o padrão chega em nós?".
