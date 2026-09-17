# GovBot, editor visual, Mapa de Riscos e geração

## Escopo e arquitetura

Implementação no Streamlit/Python existente. `src/state.py` continua sendo a
fronteira canônica: dados do formulário, documentos Markdown, aprovações,
rascunhos pendentes e autosave. Não há frontend paralelo, endpoint público,
tabela, migração ou credencial nova. A entrega não ativa configuração remota.

Base de trabalho: `56e0efa6eb740ed9a70a1d13e2c4743ecc057287`, após os reparos
de Auth da PR #20 e as alterações posteriores de provedores, processos e UI.
Branch: `feature/govbot-alertas-editor-riscos-loading`.

## Compatibilidade e flags

| Configuração existente em config_app | Ausente/falsa | Quando habilitada pelo operador |
|---|---|---|
| `flag_govbot_alertas` | Não avalia nem apresenta os novos alertas | Acrescenta alertas ao GovBot, que também depende de `flag_govbot` |
| `flag_editor_rico` | Mantém o editor histórico | Uma superfície visual, sem abas de Markdown |
| `flag_mapa_riscos` | Novos processos usam a sequência histórica | Novos processos capturam a sequência com mapa |
| `flag_loading_overlay` | Mantém o indicador histórico | Mostra estágios reais com bloqueio de interação |

Nenhuma dessas configurações é criada ou habilitada pelo código. O preview de
teste usa mocks em memória, sem chamar Supabase. A sequência escolhida fica em
`dados._fluxo_mapa_riscos`; um mapa já salvo também identifica o novo fluxo.
Processos antigos não recebem uma etapa no meio do caminho. Desligar a flag
impede a adoção por novos processos; processos que já adotaram o mapa conservam
sua sequência e a interpretação correta da etapa salva.

As constantes históricas permanecem para compatibilidade. Rotas, stepper,
progresso e exportação usam `sequencia_do_processo`/`state.sequencia`.

## Editor e formato canônico

TipTap/ProseMirror 3.31.3, com StarterKit, tabelas e extensão Markdown. Escolha
motivada por listas aninhadas, seleção, histórico, tabelas e conversão em uma
biblioteca madura. O adaptador usa Components v2; os arquivos compilados são
servidos localmente. Não há CDN. DOMPurify limpa a colagem; MarkdownIt e Bleach
limitam o HTML exibido. Scripts, iframes, handlers e URLs ativas não são aceitos
como conteúdo executável. Fonte, cor e efeitos externos não são preservados.

Markdown permanece a única representação persistida. O HTML é uma projeção
descartável para edição. O debounce de 600 ms atualiza apenas o rascunho da
sessão. Callback anterior ao roteamento conserva a edição ao navegar; os
botões do próprio editor enviam o texto atual junto da ação. Aprovação exige
clique humano. Eventos com versão/hash/contador antigos são recusados.

O GovBot recebe o rascunho Markdown por evento local de coleta. Propostas,
diffs, aplicação, auditoria e undo passam pelo núcleo existente. O mapa entra
na allowlist editorial; edital e ARP continuam restritos à correção na origem.
A nova interface não autoriza aplicar uma proposta sobre edição humana
pendente. Alterações aprovadas invalidam as peças posteriores.

O DOCX conserva ênfase, links, tabelas, quebras de célula e níveis de lista.
O PDF institucional continua sendo DOCX convertido pelo LibreOffice. O motor
alternativo não substitui a validação de fidelidade do PDF institucional.

## Alertas

`govbot_alertas.avaliar` combina validação, achados estruturados, consistência,
fatos e resultados atuais de conhecimento/qualidade. Caches de outra versão do
processo não são promovidos a achados atuais. A pesquisa aplicada fornece um
resumo dos sinais estatísticos realmente calculados, separado da planilha.
Discrepância estatística não é qualificada como ilegalidade ou sobrepreço.

Cada alerta possui id/fingerprint, versão de contexto, categoria, gravidade
INFO/ATENCAO/CRITICO, título/mensagem, documento/campo/bloco, origem, evidências,
ação sugerida e possibilidade de correção. Os aliases do formato de achados
existente são mantidos para integração. A gravidade de um alerta não cria um
novo veto jurídico; os gates objetivos de emissão continuam existentes.

Estados: NOVO, VISTO, ADIADO, RESOLVIDO e OBSOLETO. Alertas iguais não se
duplicam; nova ocorrência pode reabrir um alerta resolvido. Documento removido
pela cascata torna seus apontamentos obsoletos. Histórico encerrado é limitado
a 100 itens por bucket. Buckets continuam isolados por identidade/processo.

O painel agrupa por documento e ordena críticos primeiro. Explicar, localizar,
adiar e conferir resolução não chamam LLM. “Marcar como resolvido” exige que a
verificação confirme a resolução; se o problema persiste, a opção é corrigir
ou adiar. Sugestões semânticas seguem o fluxo de proposta existente, sem
aplicação automática. Aplicar e desfazer usam seus controles já existentes.

## Modelo fornecido e fluxo

Referência efetivamente fornecida: `MAPA_DE_RISCOS.pdf`, cinco páginas. Estrutura
preservada: identificação da necessidade em quadro, fases da análise, blocos
RISCO numerados, probabilidade e impacto qualitativos Baixa/Média/Alta, tabelas
Id/Dano, Id/Ação Preventiva/Responsável e Id/Ação de Contingência/Responsável,
local/data, Elaborado por e matrícula. Não são transplantados timbre, nomes,
município, riscos ou marcações do exemplo. Número de riscos depende do objeto.
Não se adicionam notas P×I, nível global, risco residual ou colunas alheias ao
modelo. Mapa de análise não é tratado como matriz contratual de alocação.

`DFD → ETP aprovado → mapa gerado automaticamente → revisão/aprovação humana
do mapa → TR → edital`. O contexto usa a cadeia anterior aprovada, sem tratar
rascunhos como fontes confirmadas. Alterar ETP invalida mapa, TR, edital e ARP;
alterar mapa invalida TR e instrumentos seguintes. Exportação inclui mapa
entre ETP e TR, e ARP quando o processo adota SRP.

O modo demonstração produz uma minuta explicitamente sintética, com campos a
preencher e avaliações em branco. Isso não é documento apto a emissão.

## Geração e recuperação

Estágios: PREPARANDO, GERANDO, REVISANDO, FINALIZANDO, PRONTO ou ERRO. Não há
porcentagem simulada. A revisão chama o validador determinístico. Documento
novo é candidato até o guard de versão e a substituição na sessão; edital e
ARP são preparados juntos antes de substituir o conjunto anterior.

Há exclusão mútua na instância, detecção de replay e hash de contexto. A UI
torna o restante da página inerte e as rotas/ações verificam a operação no
servidor. Foco e interação são restaurados ao fechar o indicador. Há CSS para
movimento reduzido e layout estreito. Falha de geração conserva a versão
anterior e permite nova tentativa explícita.

Limites: não é fila distribuída nem recuperação de processo após desligar o
servidor. Drafts/undo permanecem efêmeros, conforme a arquitetura existente.
A persistência remota continua sujeita ao resultado do autosave existente.

## Verificação e release

Testes Python: `python -m pytest -q -rs` (Windows: `PYTHONUTF8=1`).
Editor: na pasta `assets/rich_editor`, `pnpm install --frozen-lockfile
--ignore-scripts`, `pnpm test`, `pnpm build`. O bundle versionado deve coincidir
com o gerado. CI passa a verificar também o bundle e os testes do editor.

O CI existente exige LibreOffice Writer e PostgreSQL efêmero com pgvector,
`GOVDOCS_EXIGIR_LIBREOFFICE=1` e `GOVDOCS_EXIGIR_ENSAIO_SQL=1`. Testes pulados
localmente não contam como prova de PDF/RLS. Não usar banco real para completar
essa lacuna. A evidência final de execução fica no relatório da entrega.

Preview sintético: `streamlit run tests/manual_preview.py --server.address
127.0.0.1`. Esse arquivo não é entrypoint de produção: substitui acessos ao
banco por recusa e provedores por demonstração. A demora e a falha selecionável
existem apenas para inspecionar estados da UI.

## Rollout e rollback

Antes da ativação: CI completo verde, inspeção do PDF institucional contra o
modelo, revisão de autorização e ensaio em homologação com identidade
autorizada. Nada nesta entrega aprova migrar Auth, aplicar vínculos ou habilitar
GovBot em produção. Ativar uma flag é uma etapa operacional separada.

Rollback inicial: desligar alertas/editor/overlay pelos controles já existentes;
Markdown permanece legível no editor histórico. Desligar `flag_mapa_riscos`
impede apenas novos processos de adotarem a sequência. Não apagar mapas ou
reindexar etapas de processos existentes. Não voltar cegamente ao binário
anterior ao suporte ao mapa depois que esses processos existirem: ele não
compreende a posição das etapas nem a exportação do novo documento.

## Divergências e limites deliberados

- Apenas um PDF foi fornecido, apesar de o prompt mencionar vários.
- A ordem histórica é preservada quando a flag está desligada; a experiência
  de editor único vale no novo editor, não transforma retroativamente o legado.
- Alertas da pesquisa aparecem no wizard a partir da pesquisa aplicada; a
  pesquisa ainda em análise conserva seus próprios sinais na UI de preços.
- Não há certificação jurídica automática do conteúdo gerado. Probabilidade,
  impacto, pertinência dos riscos e responsáveis continuam sujeitos à revisão.
- A prova local sem LibreOffice/PostgreSQL não substitui os gates de release.
