# Gov Conect — Pesquisa de Preços: plano operacional de produção (09/11/2026)

## O que está efetivamente entregue nesta branch

- Política versionada `2026-11-09.teto-5.cv-25.1`: no máximo **5** referências escolhidas pela **cotação automática** por item; rodízio entre fontes elegíveis permanece.
- A seleção automática considera o CV **amostral**, usando `Decimal`, da série que formaria a cesta, **somada aos preços já incluídos por decisão humana**. CV **> 0,25** suspende **a inclusão automática da nova amostra**. CV exatamente 0,25 é permitido. Série de 1 preço não tem dispersão inferível.
- Suspensão não é exclusão jurídica nem descarte: candidatas selecionáveis ficam **gravadas para revisão**, com status `candidate`, motivo e evento de busca. Nenhuma decisão humana é revertida.
- Modo manual e pesquisas já emitidas não são modificados; o teto não é proibitivo para inclusão humana tecnicamente fundamentada.
- Regras compartilhadas nos fluxos unificado e legado; o controle é acionado com a flag `cotacao_automatica_teto`. **Código em branch/PR não significa flag ligada em produção.**

## Falha de uma fonte ≠ inexistência de mercado

O motor registra desfecho por fonte. Se todas as fontes capazes de preço falham, o item precisa indicar **erro técnico**, sem inventar amostra. Fonte que só enriquece evidência não conta como fonte de preço disponível.

## Expansão: inventário confirmado no código de 09/11/2026

| Fonte | Estado verificado | Próximo passo, sem contornar restrições |
|---|---|---|
| Compras.gov.br (preços praticados) | Adaptador de preços em `fontes_padrao()` | Auditar completude, status das APIs e evidência por contratação e item |
| PNCP | Adaptador em `fontes_padrao()`, integração de resultados por contratação conhecida | Melhorar índice de descoberta de contratações elegíveis e reconsulta de resultados no endpoint oficial; não alegar busca textual geral de preços |
| BPS — Ministério da Saúde | ETL de staging; nenhum dado habilitado | Confirmar licença de reúso comercial e política de evidência sem URL individual; validar CATMAT e itens farmacêuticos, preservar SHA-256 do ZIP |
| TCE-RS / LicitaCon | ETL de staging; nenhum dado habilitado | Licença de reúso, leiaute oficial de códigos de resultado, prova de homologação por item e deduplicação |
| Portal de Compras Públicas | Adaptador desconectado | Obter autorização, PublicKey e documentação real para resultados e itens |
| LICITANET, BLL, BNC, Compras BR, BBMNET, Licitar Digital | Cadastro de fontes; **sem adaptadores de preços** | Documentação oficial, credenciais/termos quando exigidos, um payload real e testes antes do desenvolvimento |
| TCM-PA | Cadastro sem API validada | Identificar fonte oficial estruturada e permissões de acesso/reúso |

Referências públicas verificáveis:
- [PNCP — Manual de Integração 2.6](https://pncp.gov.br/manual/pt-br/latest/singlehtml/index.html): `GET /v1/orgaos/{cnpj}/compras/{ano}/{sequencial}/itens/{numeroItem}/resultados`, para contratação **conhecida**.
- [Compras.gov.br — Manuais de Dados Abertos](https://www.gov.br/compras/pt-br/acesso-a-informacao/manuais).
- [BPS — recurso CSV 2026](https://dadosabertos.saude.gov.br/dataset/bps/resource/a07564a9-7c6c-4634-9e07-f8320088f5a6).
- Pendências históricas do repositório: `docs/fontes-precos/D_PENDENCIAS_ACESSO.md` e `B_IMPLEMENTACAO_REALIZADA.md`.

## Contrato mínimo de evidência para habilitar uma NOVA fonte

1. `fonte_id`, URL HTTPS oficial e estável para o registro ou evidência verificável de arquivo oficial + chave da linha, com procedimento documentado de reconsulta;
2. identificador único de contratação + item + resultado, órgão/CNPJ (se publicado), fornecedor (se publicado), data e modalidade/etapa de homologação comprovada;
3. descrição de objeto, CATMAT/CATSER quando houver, quantidade, unidade, valor unitário **original**, valor normalizado, regra de conversão comprovada e `natureza_valor`;
4. payload bruto imutável ou referência ao snapshot + `raw_hash` e hash do arquivo, `coletado_em`, janela temporal, correspondência e motivo para não seleção;
5. deduplicação forte quando a mesma compra aparece em portais diferentes, sem fundir observações apenas por valor parecido;
6. prova de licença/autorização, esquema documentado, exemplos reais, teste de reconsulta de pelo menos 10 itens por fonte e nenhuma divergência material sem explicação;
7. fonte habilitada **somente em staging** após esse aceite; isolamento multi-tenant/RLS, tratamento de falhas/timeout e auditoria antes da produção.

**Não elevar `licenca` para `APROVADA`, não ligar `price_source_*` e não aplicar a proposta SQL 0030 somente com base neste documento.** Esse trabalho requer comprovação.

## Implantação sem interromper serviço ao órgão

1. Rodar testes unitários, integração de cotação unificada, rota legada, emissão e regressão de fontes. Verificar quantitativos e CV exatos.
2. Em staging, pesquisar uma amostra fixa de itens normais, dispersos e sem preço; conferir visualmente a cesta, o bloqueio, as evidências e o PDF.
3. Identificar o estado real da flag `cotacao_automatica_teto` em cada ambiente; ativá-la na janela de publicação **somente depois** dos testes e monitoração. Não tocar retroativamente em cesta emitida.
4. Publicar sob rollback controlado, medindo por fonte: latência, sucesso, preços válidos, links resolvidos, rejeições por CV e duplicatas.
5. Após estabilizar o núcleo, integrar uma fonte nova por vez, com gate de rastreabilidade e comprovação de licença.

## Atenção normativa

CV > 25% é **critério de segurança operacional interno**, não um teto imposto pela legislação. A IN SEGES/ME nº 65/2021, em âmbito próprio, exige série, análise crítica, memória e justificativas; veja arts. 3º e 6º. O relatório deve evitar afirmar que toda amostra acima de 25% é ilícita ou inexequível.
