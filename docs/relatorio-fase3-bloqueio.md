# Fase 3 — BLOQUEADA antes da geração real

Branch: `integracao-padrao-ouro-main-atual`, commit `d7a1bb8`.
Data: 20/08/2026.

**Nenhum merge. Nenhum PR. Nenhuma alteração de produto nesta fase.**

A Fase 3 exige medir a qualidade REAL da geração por IA. Não há
credencial utilizável neste ambiente, e a instrução é explícita: parar
antes da geração real, documentar o bloqueio e não implementar
alterações especulativas. É o que este documento faz — e só isso.

---

## 1. Estado inicial (verificado, não presumido)

| | |
|---|---|
| HEAD | `d7a1bb8` — `ci: ausência do LibreOffice Writer passa a reprovar em CI/release` |
| árvore de trabalho | limpa |
| suíte completa (`GOVDOCS_EXIGIR_LIBREOFFICE=1`) | **1030 passaram, 0 falharam, 155 pularam** |
| motor de PDF efetivo | `libreoffice` |

Os 155 skips são os de sempre — 65 de isolamento, 50 de ensaio SQL local
e 40 de ensaio de segurança, todos exigindo banco/projeto descartável.

## 2. O bloqueio

O produto lê a chave em quatro fontes, nesta ordem (`llm._ler_chave`):
painel do administrador (banco) → sessão → `.streamlit/secrets.toml` →
variável de ambiente. **As quatro foram consultadas por PRESENÇA, nunca
por valor.** Nenhum segredo foi lido, impresso, registrado, versionado ou
derivado em nenhum momento.

| fonte | `OPENAI_API_KEY` | `GOOGLE_API_KEY` |
|---|---|---|
| painel do administrador (banco) | indisponível — `db.disponivel()` é `False` | idem |
| sessão do Streamlit | ausente | ausente |
| `.streamlit/secrets.toml` | **arquivo não existe** (só o `.example`) | idem |
| variável de ambiente | ausente | ausente |

O próprio produto confirma: `llm.motor_ativo()` devolve `''` — nem
OpenAI, nem Gemini.

E o caminho real recusa, exatamente como a documentação corrigida na
Fase 2 promete:

```
llm.gerar_documento("dfd", dados, None)   # modo_demo = False
→ ErroGeracaoIA: "Nenhuma chave de API configurada. Informe a chave da
  OpenAI (motor principal) ou do Google AI Studio na barra lateral /
  .streamlit/secrets.toml — ou ative o Modo Demonstração."
```

### O bloqueio é de credencial, não de rede

Isto importa para quem for destravar: não há firewall a abrir, não há
proxy a configurar. Os endpoints respondem — apenas recusam quem não se
identifica:

| endpoint | resposta sem credencial |
|---|---|
| `https://api.openai.com/v1/models` | **HTTP 401** (não autorizado) |
| `https://generativelanguage.googleapis.com/v1beta/models` | **HTTP 403** |

Alcance de rede: **funciona**. A única peça que falta é a chave.

### Credenciais presentes no ambiente que NÃO servem

O ambiente tem `ANTHROPIC_BASE_URL`, `CLAUDE_CODE_*`, `AWS_*`,
`GH_TOKEN` — infraestrutura da sessão de desenvolvimento, não do produto.
Não as usei, e não devem ser usadas, por três razões independentes:

1. **não são a configuração normal do projeto** — o GovDocs integra
   OpenAI (motor principal) e Gemini (fallback). Não há integração com
   Anthropic nem com Bedrock, e criar uma seria justamente a "arquitetura
   paralela" que todas as fases proibiram;
2. **mediriam outro produto** — a Fase 3 pergunta o que o usuário recebe.
   Documento redigido por um modelo que o produto não usa não responde a
   essa pergunta, responde a outra;
3. **são credenciais de sessão** — reaproveitá-las para uma finalidade
   diferente daquela para que foram emitidas não é aceitável, mesmo que
   funcionasse.

## 3. O que NÃO foi feito, deliberadamente

- **Não substituí a geração real pelo Modo Demonstração.** O Demo é uma
  minuta-esqueleto offline; apresentá-lo como prova de qualidade da IA
  seria falsear o resultado inteiro da fase. Todas as medições das Fases
  1, 2 e 2.1 que usaram Demo estão rotuladas como tal nos seus relatórios,
  e nenhuma delas afirmou nada sobre a prosa do modelo;
- **não gerei DFD, ETP nem TR**, portanto não há artefatos, matriz seção a
  seção, auditoria factual, auditoria de grounding nem veredito. Emitir
  qualquer um deles sem geração real seria inventar o dado que a fase
  existe para produzir;
- **não implementei correção nenhuma** — nem de prompt, nem de RAG, nem de
  motor de conhecimento. A fase determina diagnosticar antes de corrigir,
  e não há diagnóstico sem medição;
- **não escrevi o script de execução do fluxo real.** Seria código que
  não posso exercitar aqui; entregá-lo não testado apenas mudaria o
  bloqueio de lugar.

## 4. Como destravar

Basta **uma** credencial, por **uma** das vias que o produto já suporta.
Nada de novo precisa ser construído.

1. **Preferida — `secrets.toml`**, que já está no `.gitignore`:

   ```
   cp .streamlit/secrets.toml.example .streamlit/secrets.toml
   # editar e preencher OPENAI_API_KEY (ou GOOGLE_API_KEY)
   ```

2. **Variável de ambiente** na sessão que for rodar a fase:
   `OPENAI_API_KEY` ou `GOOGLE_API_KEY`.

3. **Painel do administrador**, se o Supabase estiver configurado — a
   chave passa a vir do banco.

Qualquer uma faz `llm.motor_ativo()` deixar de ser `''`, e é essa a
condição única para a Fase 3 começar.

**Recomendação de escopo:** use uma chave de ensaio, com limite de gasto
próprio e revogável, e não a chave de produção. A fase gera DFD, ETP e TR
completos duas vezes (antes e depois das correções) sobre um processo de
210 itens — é consumo real de tokens, e convém que ele esteja isolado.

## 5. O que já está pronto para quando a chave existir

Nada disto foi feito agora; é o que as fases anteriores deixaram no lugar
e que a Fase 3 vai usar:

- **fixture real anonimizado** — `tests/fixtures/caso_210_itens.json`,
  210 itens, R$ 8.024.834,67, com regressões determinísticas
  consolidadas (códigos de 3 a 6 dígitos, conferência por código);
- **fluxo sequencial do produto** — `gerar_documento` encadeia DFD → ETP
  → TR pelo contexto do documento anterior aprovado, com RAG, motor de
  conhecimento, famílias de modelo e `rag_trace` já ligados no caminho
  real;
- **antes × depois da correção automática** — `ciclo.executar_com_persistencia`
  devolve `documentos`, `relatorios`, `planos`, `diffs` e `eventos`, que é
  exatamente a separação entre "qualidade que nasceu na geração" e
  "qualidade que foi reparada depois" que a fase pede;
- **validadores e gate** — `validacao.validar_todos`, `achados`,
  `consistencia`, `fatos`, `qualidade`, mais a revalidação do pacote
  final antes da emissão;
- **grounding** — `validacao._validar_lastro_das_citacoes` já separa
  dispositivo canônico de dispositivo recuperado pelo RAG e acusa citação
  sem lastro;
- **artefatos** — DOCX e PDF institucionais, com o motor LibreOffice
  agora obrigatório em CI e as provas de geometria e integridade da
  tabela rodando de verdade;
- **referências do corpus ouro** — `perfis.py` carrega as metas por
  documento (≈4.800/9, ≈12.500/18, ≈11.400/17), que a fase trata como
  referência, não como gate.

## 6. Limitação que permanece registrada

A prosa real da IA **nunca foi medida** neste projeto. Isso vale para as
Fases 1, 2 e 2.1 inteiras, e continua valendo. Tudo o que foi provado até
aqui é determinístico: tabela, estrutura, validação, exportação,
geometria, separação prompt/documento, atomicidade do retry. Nenhuma
afirmação foi feita — e nenhuma pode ser feita — sobre profundidade,
raciocínio ou fundamentação do texto que o modelo escreve.

## 7. Veredito

**Nenhum.** Os três vereditos previstos para a Fase 3 —
`INFERIOR AO PADRÃO-OURO`, `EQUIVALENTE AO PADRÃO-OURO`,
`SUPERIOR AO PADRÃO-OURO EM ASPECTOS DEMONSTRADOS` — são afirmações sobre
documentos gerados. Não há documentos gerados. Emitir qualquer um deles
agora seria inventar o resultado.

**Estado da fase: BLOQUEADA — falta credencial de API.**
Retomar exatamente daqui assim que houver chave.
