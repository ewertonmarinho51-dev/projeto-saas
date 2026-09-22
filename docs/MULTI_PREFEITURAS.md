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

## Emissão: onde o cadastro vivo vira documento congelado

Enquanto o documento é rascunho, ele usa os dados atuais — se o cargo do
servidor mudar hoje, o rascunho de hoje mostra o cargo de hoje (§35). Na
**aprovação** isso para: timbrado e signatários são copiados para
`documento_identidades` e `documento_signatarios`, e a exportação passa a
ler de lá.

A diferença não é técnica, é jurídica. Um edital aprovado é ato
administrativo publicado. Se o servidor for exonerado em março, o edital
de janeiro continua tendo sido assinado por quem o assinou, com o cargo
que ele tinha — e um sistema que regenerasse o PDF consultando o cadastro
de março produziria **um documento que nunca existiu**.

| Peça | Papel |
|---|---|
| `src/emissao.py` | Lógica pura: monta snapshots, calcula o hash da identidade, renderiza o bloco. Não conhece Streamlit nem Supabase |
| `src/instituicional_bridge.py` | A única parte que conhece sessão e banco. Lê o que a sessão sabe, pede ao banco o que falta, chama `emissao` |
| `src/state.py` | Duas linhas em `aprovar_e_avancar`, **antes** de avançar a etapa |
| `src/export.py` | `gerar_docx`/`gerar_pdf` ganham `assinaturas: str = ""` |

### A assinatura que torna o erro impossível

`export.gerar_docx(titulo, texto, branding, assinaturas)` recebe o bloco
**já renderizado** — nunca uma lista de servidores a consultar. A
exportação não sabe o que é cadastro de pessoal, e é exatamente por isso
que ela **não consegue** regenerar um documento histórico com dados de
hoje. `test_a_exportacao_nao_conhece_cadastro_de_pessoal` reprova se
`export.py` passar a chamar `db.listar…`.

O bloco entra nos **dois** caminhos do PDF — a conversão por LibreOffice
e o fallback `fpdf2`. Pôr só no primeiro faria o PDF perder as
assinaturas exatamente quando o LibreOffice não estivesse disponível, e é
nesse dia que ninguém repara.

### Best-effort, deliberadamente

Falha ao congelar **não impede a aprovação** — mesma decisão que
`aprendizado.capturar_edicao` já tomou no mesmo ponto do fluxo. Travar o
avanço do processo porque uma tabela auxiliar não respondeu seria trocar
um registro incompleto por um servidor público parado.

O que a falha produz é documento sem bloco de assinatura (visível, não
silencioso) e uma linha de log. O que ela **nunca** produz é assinatura
lida do cadastro vivo na exportação: sem snapshot, sem bloco.

### A tela de seleção (§29–§32)

`src/ui/signatarios.py`, num expander **antes** do botão de aprovar. A
posição é a decisão: aprovar é emitir, e o que estiver escolhido ali é o
que fica congelado — pôr a seleção depois faria o servidor descobrir que
assinou sem escolher.

**A ordem dos dois campos é a funcionalidade.** Primeiro o **tipo** de
signatário (§29); só então os servidores elegíveis (§30). Invertida — uma
lista de gente e um campo de função ao lado — a tela viraria um
formulário onde alguém digita que o Antonio é pregoeiro, e a designação
passaria a ser afirmação do operador em vez de ato administrativo.

Com a ordem certa, "Equipe de Planejamento" mostra exatamente os membros
da portaria vigente. E quando a lista vem vazia, ela **diz por quê**:

| Causa | O que a tela diz |
|---|---|
| Sem portaria vigente | cadastre-a em Administração → Instituição → Portarias |
| Portaria sem membros dessa função | designe-os |
| Sem designação vigente | cadastre a função |
| Todos já escolhidos | todos os elegíveis já foram adicionados |

*"Nenhum servidor disponível"* mandaria o operador procurar defeito no
lugar errado — e cada uma dessas causas leva a uma ação diferente.

A tela também reordena e remove antes da aprovação (§32), **reconfere a
elegibilidade no clique** (entre montar a lista e o botão, a portaria
pode ter sido revogada) e mostra o conflito de portarias em vermelho sem
escolher nenhuma.

### Detalhes que evitam erro calado

**Só função de portaria carrega o número dela.** Carimbar
`Portaria nº 003/2026` sob o nome do Secretário Municipal seria
atribuir-lhe uma designação que a portaria não fez.

**Escolha cujo servidor sumiu do cadastro é descartada com log**, não
vira snapshot com nome vazio: bloco de assinatura sem nome é pior que
bloco ausente, porque parece assinado.

**Conflito de portarias não é resolvido no congelamento.** O documento
sai sem o número e o log registra; o painel administrativo é onde isso se
conserta.

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
descreva exatamente as tabelas que estão no banco. Enquanto a 0025 vivia
só no repositório, **não subi a contagem de 32 para 42** — isso faria o
arquivo afirmar que a migração estava aplicada, que é a mentira "para
mais" contra a qual a própria prova avisa. As dez ficaram numa lista
nomeada de **pendentes de aplicação**.

Em **18/09/2026 a 0025 foi aplicada**, e os nomes saíram de lá para a
contagem — o ato deliberado que aquele comentário previa. A contagem é
42 porque o catálogo mostra 42, e não porque o repositório quis.

---

## A aplicação em produção (18/09/2026)

Antes de escrever qualquer coisa, o pré-voo mediu: 32 tabelas, **nenhuma
das dez já existente**, nenhuma das oito colunas novas de `tenants` já
existente, RLS ligada em todas as tabelas do schema, e a 0024 presente —
que importava, porque é dela que vem o `alter default privileges`
estreitado.

**Um susto do pré-voo foi defeito da minha consulta, não do banco.** A
primeira medição acusou "1 das 8 colunas já existe"; a coluna era `uf`,
que a 0025 **não adiciona**. Eu havia listado `uf`/`municipio` no lugar
de `sigla`/`cidade`. Refeita com os nomes certos: zero colisões.

**Um risco real foi verificado e não se materializou.** Existem DOIS
defaults de privilégio no schema: o do `postgres`, estreitado pela 0024,
e um do `supabase_admin` que ainda concede TRUNCATE a `anon`,
`authenticated` e `service_role`. Qual deles vale depende de quem cria a
tabela — e a conferência da própria 0025 mede TRUNCATE só nos dois
snapshots, não nas dez. O ensaio no projeto descartável, pelo mesmo
caminho da aplicação real, mediu **zero TRUNCATE de rede nas dez**: o
`revoke truncate` explícito do arquivo cobre o caso independentemente de
qual default venceu. É a diferença entre um arquivo que afirma o estado
final e um que aplica um delta.

Pós-voo em produção, medido e não presumido:

| Medida | Resultado |
|---|---|
| Tabelas no schema `public` | 32 → **42** |
| Das dez, faltando | 0 |
| Das dez, sem RLS | 0 |
| Qualquer tabela do schema sem RLS | 0 |
| TRUNCATE para `anon`/`authenticated`/`service_role`/`PUBLIC` | 0 |
| Grants para `anon`/`PUBLIC` | 0 |
| UPDATE/DELETE/TRUNCATE nos dois snapshots | 0 |
| Políticas instaladas | 26 |
| Funções administrativas semeadas | 10 |
| `tenants` / `secretarias` / `processos` | 1 / 2 / 6 — intactos |

**A única política ampla é a prevista.** `funcoes_le` usa `using (true)`,
e o §12 proíbe isso em produção salvo justificativa arquitetural
específica para tabela realmente pública. A justificativa está escrita na
própria migração: `funcoes_administrativas` é o domínio do PRODUTO, não
de cada prefeitura — leitura para qualquer autenticado, escrita para
ninguém pela rede. Deixar uma prefeitura renomear `EQUIPE_PLANEJAMENTO`
quebraria o código que casa por esse código. A consulta ao catálogo
confirmou que ela é a única: SELECT, só `authenticated`.

**Nenhuma flag foi ligada.** Não existe linha `flag_multi_prefeituras` em
`config_app`, e ausente é desligada — a funcionalidade entrou escura. O
verificador de segurança do Supabase não acusou nada novo: os quatro
achados que ele lista são anteriores e nenhum envolve as dez tabelas.

---

## O smoke ponta a ponta (§57)

`tests/test_smoke_multi_prefeituras.py` monta o cenário literal do §57
num PostgreSQL descartável — Prefeitura Alfa, Gabinete com o brasão do
município, Administração com brasão próprio e Portaria 003/2026, Educação
sem nenhum dos dois — e percorre o caminho inteiro: banco → resolvedor de
identidade → resolvedor de portaria → elegibilidade → snapshot → bloco de
assinatura.

**Fronteira, dita antes que alguém confie demais**: roda contra o schema
REAL e atravessa a RLS com JWT de usuário autenticado, mas **não** passa
por `db.py` — que fala PostgREST por HTTP — nem por Streamlit. Prova que
schema, constraints e lógica de domínio se encaixam; não prova transporte.

### As onze provas passaram de primeira — e isso não bastava

Suíte que passa na primeira execução não provou nada até mostrar que sabe
falhar. Cada garantia foi verificada quebrando-a de propósito:

| Mutação | Resultado |
|---|---|
| `portarias.resolver` sem o filtro de secretaria | a Educação recebeu a Portaria 003/2026 da Administração — **pego**, e é a frase literal do §57 |
| `assinaturas.elegiveis` aceitando qualquer servidor | João, que nenhuma portaria designou, apareceu como elegível — **pego** |
| herança de identidade pegando a primeira da lista em vez da `padrao` | **escapou** |
| `revoke update` do snapshot removido da 0025 | **pego** pelo bloco de verificação da própria migração, que recusou aplicar |

**O mutante que escapou era um defeito da prova.** `listar_secretarias`
ordena `padrao desc, nome`, então a secretaria do município já chega
primeiro e "pegar a primeira com identidade" dá a mesma resposta que
"pegar a padrão": o teste acertava por acidente de `ORDER BY`, não por
mérito do resolvedor. Bastaria alguém mudar aquele `order` — ou o
PostgREST devolver em ordem diferente — para a Educação passar a sair com
o brasão da Administração sem um único teste reclamar.

A correção foi `test_a_heranca_escolhe_o_padrao_e_nao_a_primeira_da_lista`,
que entrega a mesma lista em ordem **hostil** (a Administração antes do
Gabinete) e exige a mesma resposta. Com ela, o mutante morre. A consulta
de produção não foi alterada: o defeito estava no que a prova assumia, não
no que o sistema faz.

### A imutabilidade do snapshot está na camada de GRANT

Uma sonda isolada concedeu `update` de volta em `documento_signatarios`
num banco descartável e refez o comando como usuário autenticado: ele
**passou**, `rowcount = 1`. Ou seja, o 42501 que o teste observa vem do
`revoke`, e não de política de RLS — a política permitiria. É informação
operacional, não defeito: significa que um `grant all on all tables in
schema public to authenticated` reabriria a edição de documento já
assinado em silêncio.

Por isso o controle é duplo e ambos existem:
`test_ninguem_altera_nem_apaga_snapshot` lê o catálogo (onde a decisão
vive) e o smoke **executa** a recusa (provando que o catálogo descreve o
comportamento). Nenhum dos dois substitui o outro.

### Guardas contra prova vazia

Três asserções no arquivo não testam o produto, testam o teste: que o
acervo lido pela Educação não está vazio (senão "nenhuma portaria vigente"
seria verdade pelo motivo errado), que o município ainda tem os três
servidores, e que a exoneração encenada alterou de fato uma linha
(`rowcount == 1`) antes de se concluir que o bloco congelado resistiu.

---

## O que NÃO está pronto

Esta entrega é a **fundação**: schema, resolvedores e provas. O que falta
é mecânico, mas é trabalho:

| Faltando | Escopo |
|---|---|
| Integração com o GovBot | §36, §37 |

O §13, o §39 e o §59 saíram em 22/09/2026 — ver a seção seguinte. O §50
(aviso de portaria em conflito, na tela onde ele se conserta) já estava
entregue com o painel administrativo.

Do GovBot ficou só o §36 e o §37, e por um motivo que vale registrar: o
texto dessas duas seções não foi preservado em lugar nenhum do
repositório. Restou a linha-resumo "integração com o GovBot", que não
diz o que integrar. Implementar por adivinhação produziria trabalho que
não corresponde ao pedido — e este projeto passou a sessão inteira
recusando exatamente isso.

---

## §13, §39 e §59 — o que saiu em 22/09/2026

### §39 — o código morto que quase virou queda de produção

`db.modulo_disponivel` existia desde a fundação, com a docstring "a
resposta que a navegação consulta", e **não era chamada em lugar
nenhum**. A navegação olhava só a flag global: uma secretaria que
desabilitasse um módulo no painel continuava vendo o item no menu.

É o mesmo padrão de `ai_gateway.telemetria`, que a 0026 foi ligar —
função escrita, provada e nunca conectada. Vale como sinal: neste
repositório, "existe uma função para isso" não quer dizer que alguém a
use.

**Ligar a função parecia trivial e não era.** `modulos_do_tenant()`
devolve `{}` para prefeitura ainda não cadastrada, e
`{}.get(modulo, False)` significa NEGADO. Em produção, onde
`tenant_modulos` está vazia, a ligação ingênua teria apagado Pesquisa de
Preços, Consolidar Demandas e Parecer Jurídico do menu de todo mundo —
uma camada criada para ORGANIZAR funcionalidade removendo
funcionalidade.

A correção está na camada que LÊ, não no resolvedor puro: ausência de
linha é "ninguém decidiu" e devolve a decisão à flag global. Recusa tem
que ser **ato** — uma linha com `habilitado = false`, gravada por alguém
no painel. `test_prefeitura_sem_cadastro_nao_perde_modulo` é a prova que
protege produção, e a mutação que devolve o default para `False` a
derruba.

### §13 — a herança, visível antes do PDF

A resolução secretaria → município → nenhuma funcionava desde antes da
0025, e era justamente esse o problema: funcionava sem que ninguém
conseguisse **ver** o resultado antes de gerar um documento. O primeiro
lugar onde a herança aparecia era o PDF assinado, e descobrir ali que a
secretaria usou o brasão errado é descobrir depois da publicação.

A seção **Timbrado** mostra, por secretaria, qual identidade sai e de
onde ela vem — e usa `contexto.resolver_identidade`, o mesmo resolvedor
da exportação, não uma segunda cópia da regra. Há prova disso: se a tela
implementasse a própria versão, as duas divergiriam e a pré-visualização
passaria a mostrar um timbrado diferente do que o PDF usaria, que é o
oposto do que ela serve para fazer.

Identidade por texto é mostrada **como texto**. Renderizar uma imitação
do documento daria uma impressão de fidelidade que ela não tem — e
fidelidade é exatamente o assunto desta tela.

### §59 — três flags, porque são três momentos

`multi_tenant_admin`, `servidores` e `portarias` controlam cada seção do
cadastro institucional. Três e não uma porque entram em produção em
momentos diferentes: cadastrar prefeitura e módulos é o primeiro dia;
servidores exige o RH ter passado a lista; portarias exige alguém
conferir o que está vigente. Uma flag só obrigaria a ligar tudo de uma
vez — ou a deixar tudo desligado esperando a parte mais lenta.

**Elas nascem LIGADAS quando ausentes**, ao contrário da
`multi_prefeituras`, que nasce desligada. A diferença é deliberada: quem
ligou a aba já decidiu usar a funcionalidade, e exigir uma segunda
decisão por seção transformaria o §59 num labirinto de caixas. Estas
flags existem para **desligar** uma seção que ainda não está pronta.

Desligar `multi_tenant_admin` leva junto **Timbrado** e **Módulos**: sem
a seção Prefeitura, as duas perdem o objeto — configuram e exibem a
prefeitura que aquela seção cadastra.

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
