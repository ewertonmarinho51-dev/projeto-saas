---
name: prova-com-dente
description: >
  Verifica se um teste realmente pega o defeito que promete pegar, por
  mutação — quebrar o código de propósito e exigir que a suíte falhe. Use
  ao escrever teste novo, ao consertar bug, ao revisar PR com teste, e
  sempre que uma prova passar de primeira sem esforço.
---

# Prova com dente

Uma prova que passa não prova nada até você ter visto ela falhar.

Isto não é princípio importado: neste repositório a mutação **pegou
defeito real** em quatro ocasiões, todas em provas que já estavam verdes.

| Mutação | O que estava escondido |
|---|---|
| `_campo` voltando a `meta["rotulo"]` | A suíte inteira passava com o rótulo errado na tela |
| `conferir` comparando o total consigo mesmo | Conferência de aritmética que não conferia nada |
| `update ... set valor = 'on'` | A prova casava com um `'on'` dentro de um comentário `--` do SQL |
| `truncate processos cascade` | A prova passava **mesmo sem a migração**, porque outra tabela negava |

## O ritual

### 1. Nomeie o defeito

Antes de escrever a prova: *que erro específico ela existe para pegar?*
Se a resposta for "testa a função X", ainda não há defeito nomeado — e
uma prova sem defeito nomeado costuma medir que o código roda, não que
ele está certo.

### 2. Quebre de propósito

Edite o código real, aplicando o defeito nomeado. Não um `assert False`
— o **erro plausível**: o operador trocado, o campo errado, a linha
removida, o default de volta.

```bash
python -m pytest tests/test_alvo.py -q   # tem que FALHAR
```

### 3. Leia a falha

Ela precisa apontar para o defeito. Uma prova que falha com
`KeyError` em vez de dizer qual valor saiu errado vai custar meia hora a
quem a encontrar vermelha daqui a um ano.

### 4. Desfaça e confirme o verde

```bash
git checkout -- <arquivo>
python -m pytest tests/test_alvo.py -q   # tem que PASSAR
```

## As três armadilhas medidas aqui

**Passar pelo motivo errado.** A prova do CASCADE passava porque o fecho
tocava uma tabela que outra migração já negava — não pelo que ela
afirmava testar. Sinal: a prova continua verde com a mudança sob teste
**inteiramente removida**. Conserto: construa o cenário dentro da prova,
para que a única causa possível de recusa seja a mudança.

**Prova vazia.** "Nenhuma linha concede TRUNCATE" é verdade num banco
vazio. Toda prova de catálogo precisa de uma âncora que garanta que o
mundo existe — `tests/test_truncate_service_role.py` abre com
`test_o_schema_real_esta_de_pe` exatamente por isso. Sem ela, uma
preparação que parasse de aplicar as migrações deixaria o arquivo
inteiro verde afirmando contenção sobre schema inexistente.

**A autodenúncia encobrindo a prova.** Quando o código sob teste tem
verificação própria — o bloco `do $$` de uma migração —, a mutação faz
ELE falhar e a suíte vira erro de preparação. Você provou que o código
se autodenuncia, não que o teste pega. Mute as duas coisas: uma vez com
a verificação ligada, outra com ela desativada.

## Skip é falha disfarçada

Um relatório cheio de "pulou" é indistinguível de um cheio de "passou"
para quem lê rápido. Onde a ausência de um requisito for falha de
ambiente e não circunstância, use os portões do projeto:
`GOVDOCS_EXIGIR_ENSAIO_SQL=1`, `GOVDOCS_EXIGIR_LIBREOFFICE=1`. O CI liga
os dois.

## Nunca

Pular, desabilitar ou pôr em quarentena um teste para ficar verde.
Afrouxar a asserção até ela passar — foi assim que o `'on'` do
comentário quase virou "a prova está errada, relaxa o casamento", quando
o certo era descartar as linhas de comentário e **provar de novo com a
mutação real**.
