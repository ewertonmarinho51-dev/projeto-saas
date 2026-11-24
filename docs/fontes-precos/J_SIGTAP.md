# J — SIGTAP: remuneração da Tabela Unificada do SUS

Estado em 24/11/2026: **implementado e testado** no branch `claude/sigtap-fonte`.
Migração `0048_precos_sigtap_referencia.sql` **não aplicada**; flag
`referencia_sus_sigtap` **desligada**; nenhuma competência importada em
produção.

## O que é, e o que não é

O SIGTAP (DATASUS) é a Tabela Unificada de Procedimentos, Medicamentos e OPM
do SUS. O valor dele é o que o SUS **remunera** ao prestador por
procedimento — não é preço de compra nem custo de obra. Por isso:

- não entra em `fontes_padrao()` nem na cesta da pesquisa de preços
  (`tests/test_sigtap.py::test_sigtap_nao_e_fonte_da_cesta_de_compras`);
- tem consulta própria, `/app/precos/sigtap`, rotulada
  "remuneração da Tabela Unificada do SUS (SIGTAP), não preço de compra";
- usá-lo como parâmetro é decisão registrada no processo, não do sistema.

## Origem oficial

| Campo | Valor |
|---|---|
| Página | https://wiki.datasus.gov.br/sigtap/index.php/Download |
| Canal | `ftp://ftp2.datasus.gov.br/pub/sistemas/tup/downloads/` (só FTP; sem HTTP/HTTPS no mesmo host) |
| Arquivo | `TabelaUnificada_AAAAMM_vAAMMDDHHMM.zip` — competência e versão da geração |
| Exemplo conferido | `TabelaUnificada_202611_v2611051737.zip`, 2.173.129 bytes, sha256 `06c074c360b0d3cdb814f19a3cdb169d9456946ba691a117982fb495505dad45` |
| Formato | texto de largura fixa, ISO-8859-1, cada tabela com `*_layout.txt` |

## O que é lido

- `tb_procedimento.txt`: código (10 dígitos), nome, complexidade e sexo como
  a fonte codifica (o leiaute não documenta rótulo: mostrados crus),
  **VL_SH, VL_SA, VL_SP** com duas casas implícitas, financiamento, rubrica e
  a competência de cada linha;
- `rl_procedimento_modalidade` + `tb_modalidade`: Ambulatorial, Hospitalar,
  Hospital Dia, Atenção Domiciliar;
- `tb_financiamento`, `tb_rubrica`, `tb_grupo`, `tb_sub_grupo`,
  `tb_forma_organizacao`: os nomes.

Totais como os relatórios do SIGTAP: **total ambulatorial = SA**; **total
hospitalar = SH + SP**. Valor zero é dado da tabela (ex.: atividade
educativa), mostrado como "sem valor unitário na tabela".

Escala conferida com a consulta pública: glicose (02.02.01.047-3) SA R$ 1,85;
consulta especializada (03.01.01.007-2) SA R$ 10,00; cesariana
(04.11.01.003-4) SH R$ 395,68 + SP R$ 150,05 = R$ 545,73.

Medição em 11/2026: 5.068 linhas, 5.068 válidas, 902 sem valor unitário,
nenhuma recusa; reimportar o mesmo arquivo = `ja_publicado`.

## Integridade (o canal é FTP sem criptografia)

- o baixador só fala com `ftp2.datasus.gov.br`, só na pasta da Tabela
  Unificada, só pede arquivo com o nome da publicação e para em 50 MB;
- o ZIP passa por `arquivos.conferir_zip` (extensões `.txt`, `.xls`, `.inf`
  e sem extensão; até 150 entradas; nada é executado);
- o leiaute embutido de cada tabela tem de ser **igual** ao esperado
  (coluna, início, fim) — mudou, não importa nada;
- a competência do nome tem de ser a pedida e a de **cada** linha;
- código único e numérico; valor legível; recusa por linha com motivo;
- SHA-256 e versão do nome gravados; arquivo que encolheu abaixo de 50% da
  versão publicada é recusado e a anterior fica.

Risco residual: um arquivo trocado no caminho que respeite leiaute,
competência e formato passaria. Mitigação operacional: conferir por amostra
na consulta pública do SIGTAP depois de importar (como acima).

## Banco (0048)

`precos_sigtap_versoes` (controle da importação, só servidor) e
`precos_sigtap_procedimentos` (leitura de `authenticated` só do vigente).
Sem `tenant_id`; `service_role` sem DELETE/TRUNCATE/REFERENCES/TRIGGER;
RPC `precos_sigtap_buscar(termos, codigo, competencia, modalidade, limite)`
`security invoker`, `search_path` vazio, 24 termos × 60 caracteres, até 200.

## Operação (quando autorizado)

1. aplicar a 0048 pelo ritual (`revisar-migracao`);
2. no servidor, com `SUPABASE_URL` e `SUPABASE_SERVICE_KEY` do ambiente:
   `python -m src.precos.sigtap_servico importar --competencia 2026-11 --banco`
   (ou `--zip <arquivo com nome oficial>`);
3. conferir por amostra na consulta pública;
4. ligar `flag_referencia_sus_sigtap = on`; rollback: `off`.

## Provas

- `tests/test_sigtap.py` — leitura sobre amostra real, conferências,
  importação por versão, consulta, baixador;
- `tests/test_migracao_0048.py` — RLS, grants, busca e a conferência que
  morde (PostgreSQL do CI);
- `apps/api/tests/test_precos_referencias_sigtap.py` — rota, flag, filtros;
- `apps/web/e2e/sigtap.spec.ts` — a tela contra a pilha real, com quatro
  procedimentos reais de 11/2026.
