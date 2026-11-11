# Cotação automática multiportal — homologação e liberação do piloto

10/11/2026. Pilha: #187 → #188 → #189 → #190 → #191 (#192, Curitiba, fica fora do piloto).

## Homologação (dados públicos reais, sem dado de produção)

O mesmo lote de 40 itens foi rodado nas duas versões do código, com as mesmas
fontes: **Compras.gov ao vivo** (API pública) e o **índice do PNCP do Pará**,
lido de um arquivo gerado pelo coletor contra a API pública (822 resultados
homologados, 263 contratações fora do Compras.gov). O lote tem os 7 casos do
piloto do #188 (gasolina, diesel S10, arroz, açúcar, feijão, papel A4, água
20 L) e os 33 primeiros itens da planilha real versionada
(`tests/fixtures/caso_210_itens.json`). Banco: o dublê das provas; nada foi
gravado fora da memória.

- **Antes**: #188 (7baa580), com o índice ligado e sem expansão nem equivalência.
- **Depois**: esta pilha (5a32347).

| | Antes | Depois |
| --- | ---: | ---: |
| Itens com preço proposto | 7 | **9** |
| Itens que perderam o preço | — | 0 |
| Referências únicas (soma) | 3.947 | 4.347 |
| Elegíveis (soma) | 763 | 753 |
| Referências na cesta, Compras.gov / PNCP | 30 / 5 | 40 / 5 |
| Tempo total / p95 por item | 89 s / 5,7 s | 135 s / 9,2 s |

**O que mudou de verdade:**

- **Cobertura.** Dois itens passaram a ter preço proposto: o caderno brochura capa dura grande (0 → 14 elegíveis, atributos conferidos) e a bateria CR2032 (43 → 51). Nenhum item perdeu o preço.
- **Variante.** O caderno com arame foi de 1 para 15 elegíveis pela rodada das variantes locais. Ainda está bloqueado pelo CV, então o ganho é de cobertura e falta revisão.
- **Fora do Compras.gov.** Gasolina e diesel têm 5 referências do índice PNCP na cesta, todas com origem Licitanet · Coleta via PNCP.
- **Mais candidatos não é mais cobertura.** As referências únicas subiram 10% (fase de variantes). Os elegíveis caíram 1%, porque a equivalência tirou da elegibilidade 137 incompatíveis e mandou 1.485 similares para a revisão. Exemplos: água de 500 ml contra 20 L; cola de 100 g contra 8 g; catálogo que não comprova a massa.
- **Desfechos do depois:** revisar CV 20, pronto para revisão 9, revisar similaridade 7, sem referência compatível 4.

**O que segue sem solução:**

- **Papel A4.** Não há linha no índice paraense medido, então é problema de cobertura da fonte, não de busca.
- **CV.** O maior bloqueio é a barreira do CV (#187): 20 dos 40 itens vão para "revisar CV".
- **Latência.** O p95 subiu de 5,7 s para 9,2 s por causa da rodada extra nos itens de amostra curta.

## Pronto para produção

O CI está verde e tudo nasce desligado ou é retrocompatível:

- origem e canal separados; revisita do índice; serviço indexador (perfil próprio);
- equivalência e expansão local (sem IA: `precos_ia_termos` desligada);
- importação que inicia a cotação; worker que fixa o recorte, retenta falha transitória com limite e reavalia pendência com dado novo;
- lista priorizada; aceite das propostas aptas em "Concluir cotação".

## Sequência de liberação

Os passos 1 a 4 exigem **aceite do dono**: a migração 0042 cria leitura nova para `authenticated` e o indexador pede credencial de servidor. A promoção da imagem já está coberta pela autorização vigente de 29/10.

1. **Merge na ordem** #187 → #188 → #189 → #190 → #191, cada um com CI verde (o Vercel não conta). Fechar o #184 como substituído.
2. **Migração 0042 em produção**, pelo ritual `revisar-migracao`: medir antes, aplicar por `apply_migration` com o nome `m0042_precos_pncp_indice` e medir depois. Já foi ensaiada no CI e no projeto descartável, com amostra real. Atualizar o cabeçalho com a data do registro.
3. **Imagens e promoção**: workflow "Gov Conect - imagens" (`ambiente=production`), depois `sudo ./promover_govconect.sh --atual` e `sudo ./promover_govconect.sh sha-<novo> production`.
4. **Indexador**: o dono cria `/etc/govdocs/indexador.env` (`SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `INDEXADOR_UFS=PA`, `chmod 600`). Depois, `docker compose --profile indexador up -d indexador-pncp`. Na primeira rodada (logs do serviço), conferir uma amostra contra o edital no PNCP.
5. **Flag PNCP**: `price_source_pncp_indice = 1` em `config_app`.
6. **Primeira rodada no ambiente alvo**: em uma cotação real da prefeitura (só leitura), conferir na trilha `busca_concluida.desfechos.pncp` e a origem das referências.

## Fica desligado

- **IA** (`precos_ia_termos`): o orçamento já está definido (1 pedido por item, 20 por execução). Só ligar depois de medir o `ganho_ia` nos itens insuficientes.
- **Curitiba** (`price_source_curitiba`, #192): o portal respondeu 503 em 10/11. Ligar só depois de validar o CSV real e as evidências.

## Reversão

- **Fonte**: `price_source_pncp_indice = 0`.
- **Indexador**: `docker compose stop indexador-pncp`.
- **Imagem**: `sudo ./promover_govconect.sh sha-<anterior> production --voltar`.
- **Migração**: as tabelas novas ficam vazias e sem uso com a flag desligada; não há DROP.
