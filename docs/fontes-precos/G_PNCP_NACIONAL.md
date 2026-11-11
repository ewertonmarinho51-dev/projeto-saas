# PNCP nacional sob demanda

11/11/2026. Fonte `src/precos/pncp_nacional.py`, flag `price_source_pncp_nacional` (nasce desligada).

## Por quê

O dono rodou a mesma cotação no Banco de Preços e aqui. Para "analisador bioquímico", o Banco de Preços trouxe dezenas de resultados homologados de CE, PE, GO, MT, MA, MG, RS, SP e RJ, de até um ano. Aqui não veio nenhum. No mesmo dia, o índice do PNCP (`precos_pncp_resultados`) tinha **141 resultados vigentes, todos do Pará, nenhum "analisador"**.

## O que foi medido antes de escolher o caminho

| Caminho | Medida | Conclusão |
| --- | --- | --- |
| Ampliar o índice (`pncp_indice`) para 27 UFs e 12 meses | O PNCP publicou 31.934 pregões eletrônicos e 634 presenciais em out/2026 no Brasil, contra 536 no Pará. São cerca de 390 mil contratações por ano, e o resultado custa 1 chamada **por item** | Não cabe: milhões de chamadas e de linhas no banco |
| Lote de resultados do Compras.gov (`dadosabertos…/3_consultarResultadoItensContratacoes_PNCP_14133`) | 9.761 resultados num dia, 500 por página, em 0,6 s; mas o CNPJ de Santana do Araguaia voltou com **zero** registros | Só cobre órgão federal |
| Busca do portal (`pncp.gov.br/api/search/`) | "analisador bioquimico" com `modalidades=6\|7`, `status=encerradas` e `tem_resultado=true` devolveu 1.178 contratações, 18 UFs na 1ª página | **Escolhido** |

## Como funciona

1. A busca usa o **núcleo** da descrição: as primeiras palavras significativas, na ordem. Ficam de fora medida e embalagem (saco, resma, folhas) e número puro; formato com letra e número (A4, 75g) fica. Quando há termo alternativo da expansão, o primeiro também é buscado.
2. Entram só pregões eletrônicos e presenciais encerrados, com resultado, não cancelados e da UF da pesquisa. Sem UF, a busca é nacional. A dispensa fica fora, pelo mesmo motivo do índice: dado pessoal.
3. Cada contratação passa por `pncp.PNCPContratacao` (a conferência de #187) com o cabeçalho que a busca já trouxe, sem chamada à API de consulta. Só entram os itens que **começam** pelo nome do item consultado e contêm o qualificador. Assim saem, medido em produção: "lâmpada… para analisador", "desproteinizante para analisador", o analisador de hematologia, "papeleira" e "envelope em papel".
4. O resultado só vira referência se unitário × quantidade bater com o total, se não for julgado por maior desconto e se não estiver cancelado.
5. Referência fora da janela da pesquisa não entra. A janela continua sendo a da **pesquisa**, 180 dias por orientação do órgão em 14/10/2026; esta fonte não a altera.
6. A fonte para ao atingir 15 referências (ou o limite por fonte da política), lendo no máximo 16 contratações e 2 itens por contratação.

## Limite de taxa

O PNCP responde **HTTP 429** a rajadas: 4 chamadas em paralelo bastaram, inclusive na API de consulta. Por isso a fonte:
- faz uma chamada por vez no processo, com 0,35 s de intervalo;
- respeita o `Retry-After` (até 10 s);
- tenta de novo em conexão recusada e em 5xx, até 4 vezes.

Custo medido por item: 20 a 35 chamadas, de 9 a 16 s.

## Com o índice regional

Com a flag nacional ligada, ela **substitui** o índice na resposta por `pncp`, porque o índice é um subconjunto dela. O indexador continua coletando; desligar a flag nacional devolve o índice à busca.

## Risco

A busca do portal é a que o site usa, não a API de consulta documentada. Se mudar de contrato, a fonte falha com recado (`falhar`) e a pesquisa segue nas demais fontes. Nunca inventa preço.

## Liberação e reversão

- Ligar: `flag_price_source_pncp_nacional = on`.
- Reverter: valor `off`. A próxima busca volta ao índice, ou ao adapter de evidência se o índice também estiver desligado. Referência já gravada não muda.

## Homologação (11/11/2026): ainda NÃO liberar

Usei o mesmo lote de 40 itens do doc F, mais o analisador bioquímico. As fontes eram reais: Compras.gov ao vivo e a fonte nacional no lugar do índice do Pará. O banco era o dublê.

| | Índice PA | Nacional |
| --- | ---: | ---: |
| Itens com preço proposto | 9 | 8 |
| Referências PNCP na cesta | 5 | 9 |
| Itens com a fonte PNCP em **falha** | 0 | **18 de 41** |
| Tempo total / mediana / p95 por item | 135 s / ~3 s / 9 s | 1.487 s / 31 s / 88 s |

- **Funciona quando responde.** Ganharam preço: cola bastão (5 do PNCP na cesta), bateria 9 V (3), apontador e clipe. As referências vêm de prefeituras de vários estados, como faltava.
- **Ainda não serve sob carga.** Com ~30 chamadas por item em sequência, o PNCP passa a recusar conexão na busca e a fonte falha em 44% dos itens. Item com fonte em falha fica pendente para nova tentativa, por isso 5 itens que tinham preço voltaram como "amostra insuficiente" com os mesmos elegíveis.
- **Analisador bioquímico**: a fonte achou os resultados de PA, MG e AM, mas a cesta não fechou (amostra insuficiente). O equipamento varia de R$ 12 mil (semiautomático) a R$ 270 mil (automático 620 testes/h).

## O caminho adotado: o indexador busca pelos itens cotados (0043)

Como a busca nacional no clique não aguenta a carga, ela passou para o **indexador**:

1. A cada ciclo, depois das UFs, `rodada_por_termos` lê as descrições cotadas nos últimos 30 dias (`pesquisa_preco_itens`, só a coluna `descricao`, com a credencial de servidor). Tira o **núcleo** de cada uma e registra os núcleos novos em `precos_pncp_termos`.
2. Busca os termos que estão na vez, os nunca buscados primeiro, pela busca do portal: pregões encerrados com resultado, publicados nos últimos 485 dias (1 ano da IN 65 mais a folga até o resultado).
3. De cada contratação achada (até 16 por termo), `Coletor.indexar_termo` lê os itens e, dos que **começam** pelo nome do item, até 3 resultados. Grava pela mesma `linha_do_resultado` da coleta regional: mesma conferência, mesma quarentena, mesmo maior desconto fora.
4. A contratação fica `parcial`, com os termos já lidos. Se a descoberta regional a achar depois, ela volta à fila da leitura completa.
5. O termo volta em 7 dias; se falhou, em 6 h. Se o orçamento acabar no meio, o termo fica para a próxima rodada.

**A cotação não muda:** a fonte do índice (`price_source_pncp_indice`, ligada) lê pela RPC, com o JWT do usuário, e passa a achar resultados do Brasil inteiro. A flag da fonte ao vivo (`price_source_pncp_nacional`) fica **desligada**; o código dela serve ao indexador (núcleo, filtro de item, cabeçalho, parâmetros).

**Medido em 11/11/2026, na bancada:**
- ~33 chamadas e ~45 s por termo, rendendo ~10 resultados novos;
- "analisador bioquímico" passou de 0 para 10 referências (AM, MG, PA, RS) dentro da janela de 180 dias.

O padrão por ciclo é de 2.000 chamadas e 80 termos (~45 min). A cada 6 h, isso dá ~240 termos por dia.

**Privacidade (revisão de banco de 11/11/2026):**
- A leitura cruza órgãos por desenho, mas só o núcleo sai do processo. O núcleo descarta:
  - número puro;
  - palavra com e-mail;
  - formato longo com dígitos;
  - o verbo da compra ("aquisição", "contratação", "empresa"), que viria antes de um nome próprio numa descrição de serviço.
- O servidor pode apagar um termo gravado por engano.

**Homologação do caminho adotado (11/11/2026).** Usei o mesmo lote de 40 itens, com Compras.gov ao vivo e o banco dublê. O índice de bancada era o do Pará (822 resultados) mais a busca por termo dos 41 núcleos do lote: 1.264 chamadas em 28 min, que chegaram a **1.191 resultados de 24 UFs**. O controle, rodado no mesmo dia e com o mesmo código, usou o índice só do Pará, porque o Compras.gov ao vivo muda de um dia para o outro.

| | Índice só do PA | Índice + busca por termo |
| --- | ---: | ---: |
| Itens com preço proposto | 7 | 7 (feijão ganhou, caderno capa dura grande perdeu) |
| Itens com mais elegíveis | — | 15 de 40 |
| Fonte PNCP em falha | 0 | 0 |
| p95 por item | 12,5 s | 15,3 s |

Os elegíveis cresceram em 15 itens, entre eles cola bastão (0→5), bateria 9 V (0→3), bloco adesivo (0→4), água 20 L (2→6) e caderno pequeno (15→34). O preço proposto não subiu porque o que segura a cesta continua sendo a amostra mínima e o CV (doc F: 20 de 40 barrados pelo CV), não a falta de fonte.

**Desligar:** rodar o ciclo com `--sem-termos`. O que já está no índice continua valendo pela conferência de sempre.
