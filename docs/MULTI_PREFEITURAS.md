# Multi-prefeituras: módulos, servidores, portarias e assinaturas

**18/09/2026.** Fundação da arquitetura institucional multi-prefeituras.
Branch `feature/multi-prefeituras-servidores-portarias`, a partir de
`48bc3d1`.

**Estado: NÃO APLICADO EM PRODUÇÃO, não mergeado, flags desligadas.**

---

## O que já existia — e por isso não foi recriado

A auditoria do schema encontrou pronto mais do que o escopo supunha:

| Peça | Estado encontrado |
|---|---|
| `tenants` | id, slug, nome, uf, ativo |
| `secretarias` | tenant_id, nome, sigla, ativo, **identidade visual completa** (cabeçalho/rodapé/marca + `_img` + `_pct`, `padrao`) e `origem_orgao_id`, o espelho do legado `config_orgaos` |
| `usuarios` | tenant_id, secretaria_id, papel, papel_governanca, auth_user_id |
| `processos` | tenant_id, secretaria_id, auth_user_id, dados, documentos, snapshot |
| **Resolvedor de identidade** | `src/contexto.py:81` — a herança **secretaria → município → nenhuma** já estava implementada e testada |
| **Contexto institucional** | `contexto_institucional()` já deriva tenant e secretaria **da sessão autenticada**, nunca do formulário |
| **Trilha de auditoria** | `governanca_eventos` + `registrar_evento_governanca()` |
| **Auxiliares de RLS** | `tenant_do_jwt()`, `secretaria_do_jwt()`, `e_admin()`, `pode_ler_processo()` |

Os §11, §12 e §26 do escopo — herança de timbrado e contexto
institucional — **já estavam resolvidos**. Nada foi duplicado: a 0025 dá
dados novos ao resolvedor existente, não um concorrente.

O §48 (auditoria) se resolve em `governanca_eventos`. O §4 (tenant nunca
vem do frontend) já é garantido por `contexto.py`.

---

## A descoberta que muda o modelo do escopo

O escopo lista `documentos` como se fosse tabela. **Não é.** Os
documentos vivem em `processos.documentos`, uma coluna jsonb, e
`processos.snapshot` guarda o bundle de blocos versionados.

Criar uma tabela `documentos` agora significaria duas verdades sobre onde
o documento mora, e elas divergiriam na primeira edição feita pela tela
de sempre — exatamente o que a 0023 recusou fazer com a consolidação de
demanda.

Por isso as duas tabelas de snapshot são chaveadas por
**`(processo_id, doc_key)`**, que é como o documento é de fato
identificado neste sistema.

---

## O que a migração 0025 cria

Dez tabelas, todas com RLS, FK, índice e `tenant_id`:

| Tabela | Escopo | Papel |
|---|---|---|
| `tenant_modulos` | §9 | Módulo habilitado por prefeitura |
| `secretaria_modulos` | §10 | HERDAR / HABILITADO / DESABILITADO |
| `servidores` | §15 | Cadastro institucional |
| `servidor_vinculos` | §16 | Histórico de lotação |
| `funcoes_administrativas` | §17 | Domínio fechado, semeado com 10 funções |
| `servidor_funcoes` | §18 | Designação, com origem e vigência |
| `portarias` | §19, §20 | Tipo aberto além de Equipe de Planejamento |
| `portaria_membros` | §22 | FK para servidor, nunca nome em texto |
| `documento_identidades` | §14 | Snapshot do timbrado |
| `documento_signatarios` | §33 | Snapshot da assinatura |

Mais oito colunas **nullable** em `tenants` (§8). Nenhuma linha existente
é alterada; `add column` com default nulo não reescreve tabela no PG 11+.

### Decisões registradas

**Sem CPF em `servidores`.** O escopo diz "não exigir CPF se não houver
necessidade funcional", e não há: o documento precisa de nome, cargo,
matrícula e função. CPF guardado "por via das dúvidas" é obrigação de
LGPD adquirida sem contrapartida.

**`status` da portaria é declarado, não derivado da data.** Parece
redundante com a vigência e não é: uma portaria pode ser **revogada
antes** do fim da vigência, e nenhuma conta de data descobre isso. O
resolvedor usa os dois.

**Vínculo em tabela própria, não `servidores.secretaria_id`.** Servidor
muda de secretaria, e um documento de 2025 precisa dizer onde ele estava
em 2025. Guardar só o vínculo corrente faria o histórico mentir na
primeira transferência.

**Snapshot é imutável no banco.** Sem `UPDATE`, `DELETE` nem `TRUNCATE`
para `authenticated`, `anon` **ou `service_role``. A correção de um erro
é emissão nova com `versao` maior, não reescrita. Mesma decisão da 0020
para `governanca_eventos`.

> A primeira versão do arquivo esqueceu `service_role` no revoke. **A
> conferência da própria migração pegou**, nomeando as quatro concessões
> que sobravam. É a lição da 0021 de novo: o default do Supabase concede
> `arwdDxtm`, então *não escrever a linha* não significa *não conceder*.

---

## A herança de módulo (§10)

Três níveis, e nenhum deles é sistema novo:

```
flag global (config_app)  → o módulo existe no produto
tenant_modulos            → esta prefeitura contratou
secretaria_modulos        → esta secretaria usa
```

A conjunção é obrigatória e a ordem importa: **nível de baixo nunca abre
o que o de cima fechou.**

| Flag global | Tenant | Secretaria | Resultado |
|---|---|---|---|
| desligada | qualquer | qualquer | **desligado** |
| ligada | desligado | qualquer | **desligado** |
| ligada | ligado | HERDAR | ligado |
| ligada | ligado | HABILITADO | ligado |
| ligada | ligado | DESABILITADO | **desligado** |

Estado inválido vindo do banco cai em `HERDAR` — devolve a decisão ao
nível de cima, que é a escolha conservadora. `HABILITADO` por corrupção
concederia acesso.

`modulos.explicar()` existe porque "o menu não mostra" é a pior forma de
indisponibilidade: o servidor não sabe se o sistema não tem, se a
prefeitura não contratou ou se a secretaria dispensou — e cada caso leva
a uma ação diferente.

---

## A data de referência (§24) — a regra escolhida

**A portaria é resolvida pela data de CRIAÇÃO do processo
(`processos.criado_em`), não por "hoje".**

Por quê: um DFD de janeiro cita a Equipe de Planejamento designada pela
portaria que valia em janeiro. Se o sistema perguntasse "qual a portaria
ativa hoje?", o documento reaberto em dezembro passaria a citar outra — e
o documento histórico mentiria sobre o ato que o fundamentou.

Não há função neste módulo que use `hoje` por default escondido: quem
chama declara a data.

---

## Conflito de portaria: erro, nunca arbítrio (§23)

Duas portarias do mesmo tipo vigentes na mesma secretaria na mesma data
levantam `PortariaAmbigua`, com os números das duas na mensagem.

Escolher em silêncio — a mais recente, a de número maior — produziria um
documento citando uma portaria plausível, assinado pelo servidor, com o
erro aparecendo só numa auditoria do tribunal de contas. Duas portarias
vigentes é **defeito de cadastro**, e cadastro com defeito se conserta no
painel.

---

## Nunca inventar portaria (§27)

Sem portaria vigente, a citação sai como
`[PREENCHER: número e data da Portaria da Equipe de Planejamento desta
secretaria]` — o mesmo marcador que o gerador já usa para dado faltante,
e que a revisão transforma em pergunta ao servidor.

`test_sem_portaria_o_documento_recebe_MARCADOR_e_nunca_um_numero` mede
isso com uma regex que reprova qualquer `nº <dígito>` no texto de
ausência.

---

## Elegibilidade de signatário (§30, §31)

A lista **não** é "todos os servidores do município". É quem tem aquela
função, naquela secretaria, vigente naquela data.

- **Equipe de Planejamento e coordenação**: a fonte é a **portaria
  vigente**. Sem portaria, a lista é **vazia** — e vazia é a resposta
  certa: nomear alguém "integrante da equipe" sem ato que o designe é o
  erro que o documento carrega para o processo.
- **Demais funções**: `servidor_funcoes` com vigência na data e
  secretaria compatível.
- **Função municipal** (`secretaria_id` nulo): alcança qualquer
  secretaria do tenant — é o caso da autoridade competente.

O coordenador **também** aparece entre os integrantes: pedir integrantes
e esconder quem coordena produziria uma lista que não bate com a portaria
publicada.

`conferir_elegibilidade()` revalida **na hora de gravar**, não só ao
montar a lista: entre a tela e o clique, a portaria pode ter sido
revogada.

---

## Isolamento, medido (§45)

`tests/test_multi_prefeituras_rls.py` aplica o schema real num PostgreSQL
descartável, injeta o JWT em `request.jwt.claims` — o que o PostgREST faz
— e mede cada fronteira com **duas prefeituras**, porque com uma só toda
consulta volta vazia e toda prova passa.

| Fronteira | Resultado |
|---|---|
| Alfa não vê servidor de Beta | ✅ |
| Alfa não vê portaria de Beta | ✅ |
| Alfa não vê membro de portaria de Beta | ✅ |
| Alfa não vê secretaria de Beta | ✅ |
| Admin de Alfa não cadastra servidor em Beta | ✅ 42501 |
| Admin de Alfa não cria portaria em Beta | ✅ 42501 |
| Usuário comum não cadastra servidor | ✅ 42501 |
| Usuário comum **lê** servidores da própria prefeitura | ✅ |
| Snapshot sem UPDATE/DELETE/TRUNCATE para papel de rede | ✅ |
| `anon` não alcança nenhuma tabela nova | ✅ |
| Prefeitura não escreve no domínio de funções | ✅ 42501 |

**Mutações verificadas**: a política de leitura virando `using (true)` —
o pesadelo do achado P0 de agosto — derruba 4 provas; a escrita deixando
de exigir `e_admin()` derruba 1.

---

## A camada de acesso (`db.py`)

Quinze funções, e **nenhuma aceita `tenant_id` por parâmetro**. O tenant
vem sempre de `tenant_atual()`, que deriva do vínculo do usuário
autenticado.

A RLS da 0025 recusaria de qualquer jeito — mas um parâmetro opcional de
tenant é um convite a alguém passá-lo a partir da tela, e no dia em que
isso acontecesse o código já teria sido escrito e revisado como se fosse
aceitável. Melhor que a assinatura torne o erro impossível de digitar.
Duas provas guardam isso: nenhuma função aceita tenant de fora, e toda
função de escrita cita `tenant_atual()`.

`modulo_disponivel()` é a função que a navegação consulta — os três
níveis de uma vez. Falha de banco devolve o valor da **flag global**, e
não `False`: o módulo sumir do menu porque o Supabase piscou seria uma
queda de funcionalidade causada pela camada que existe para organizá-la.

---

## O painel administrativo

`src/ui/instituicional.py`, ligado como **uma aba** em `admin.py` — não
quatro. O painel já tinha seis; dez abas no topo seria a "Administração
virando ERP gigantesco" que o §7 proíbe, e empurraria *Usuários* e
*Chaves de IA* para fora do campo de visão de quem abre a tela. A
navegação é em dois níveis: a aba **Instituição** com um seletor interno
de quatro seções.

| Seção | O que faz | Escopo |
|---|---|---|
| Prefeitura | Dados institucionais, todos opcionais | §8 |
| Módulos | Habilitação por prefeitura e o estado por secretaria | §9, §10 |
| Servidores | Cadastro e ativação | §15 |
| Portarias | Registro, situação, membros e histórico | §19–§22, §52, §54 |

**A aba só existe com `flag_multi_prefeituras` ligada, e a flag nasce
desligada.** Sem a 0025 aplicada as consultas falhariam de qualquer jeito
— e uma aba que só sabe explicar por que não funciona é pior que aba
nenhuma. Quando a migração falta, `_exigir_migracao()` diz **qual
arquivo** aplicar, em vez de deixar vazar um erro de PostgREST sobre
relação inexistente.

### Decisões da tela

**Módulo indisponível no produto não aparece como caixa desmarcada** —
aparece como *"indisponível nesta versão do sistema"*. Uma caixa que o
administrador marca e que não liga nada levaria semanas para ser
descoberta.

**O aviso de conflito de portarias vive na tela onde ele se conserta**
(§50). Duas portarias vigentes do mesmo tipo aparecem em vermelho na
lista, com os dois números. Deixar o erro só para a hora de gerar o
documento adiaria a descoberta para o pior momento possível.

**Não há campo de texto livre no cadastro de membro** (§53). Só um
seletor de servidores já cadastrados: criar pessoa nova por dentro de uma
portaria produziria dois "Antonio" que o sistema não sabe serem o mesmo,
e o snapshot do documento apontaria para o errado.

**Portaria nova nasce RASCUNHO**, nunca ATIVA. E a situação declarada
oferece só RASCUNHO, ATIVA e REVOGADA — EXPIRADA e FUTURA são efeito da
vigência, que o sistema calcula sozinho; oferecê-las para escolha
convidaria alguém a declarar uma coisa que as datas contradizem.

---

## Dois defeitos que a suíte existente pegou

**O inventário de segurança lia comentário como comando.** A 0025 explica
no texto dela que *"`create table if not exists` que não cria não levanta
erro"* — e o extrator de `scripts/ensaio_seguranca.py` leu a frase como
comando. O backtick depois de `exists` impediu o grupo opcional de casar,
a expressão recuou, e uma **tabela chamada `if`** entrou no inventário.

Não é curiosidade: esse inventário é o que a varredura de contenção sonda
e o que alimenta a prova que conta as tabelas em produção. Descartar `if`
na saída trataria o sintoma; o defeito era ler comentário como código, e
foi isso que se consertou.

**A contagem de tabelas em produção.** A prova exige que o inventário
descreva exatamente as 32 tabelas que estão no banco. Com a 0025 no
repositório, ele passou a descrever 42. **Não subi a contagem para 42** —
isso faria o arquivo afirmar que a 0025 está aplicada, que é a mentira
"para mais" contra a qual a própria prova avisa. As dez entraram numa
lista nomeada de **pendentes de aplicação**, e quem aplicar a migração
move os nomes de lá para a contagem — ato deliberado, igual ao cabeçalho
que a 0018, a 0019 e a 0020 passaram a declarar depois de aplicadas.

---

## O que NÃO está pronto

Esta entrega é a **fundação**: schema, resolvedores e provas. O que falta
é mecânico, mas é trabalho:

| Faltando | Escopo |
|---|---|
| Pré-visualização de timbrado | §13 |
| Tela de seleção de signatários | §32 |
| Gravação do snapshot no fluxo de aprovação | §35 |
| Leitura dos snapshots na exportação DOCX/PDF | §34 |
| Integração com o GovBot | §36, §37, §50 |
| Ocultar módulo indisponível na navegação | §39 |
| Flags `multi_tenant_admin`, `servidores`, `portarias` | §59 |
| Smoke ponta a ponta com as duas secretarias | §57 |

A ordem importa: a fundação primeiro porque erro de schema e de RLS é
caro e difícil de reverter; a tela é mecânica sobre uma base provada.

---

## Rollout e rollback

**Rollout**: aplicar a 0025 em ensaio → aplicar em produção → cadastrar
prefeitura, secretarias, servidores e portarias → ligar as flags por
tenant → só então trocar o campo livre de assinatura pela seleção
institucional (§28: não remover o legado sem compatibilidade).

**Rollback**: as flags desligam a funcionalidade sem tocar no schema. As
dez tabelas ficam inertes — nenhuma coluna existente foi alterada,
nenhum dado foi movido, `config_orgaos` e `secretarias` não foram
tocados. Processos antigos seguem pelo caminho legado (§58).
