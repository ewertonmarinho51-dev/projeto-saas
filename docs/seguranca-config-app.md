# Exposição do banco pela chave publicável — diagnóstico e plano

**Achado em 14/08/2026**, durante a auditoria do padrão ouro documental.
Ampliado no mesmo dia para todas as tabelas, grants, políticas, views e
funções, a pedido da auditoria independente.

**Estado: nada foi aplicado.** Nenhum SQL executado, nenhuma chave
rotacionada, nenhuma alteração em produção. Este documento e a migração
`0018_…sql.NAO_APLICAR` existem para revisão.

---

## 1. Resumo executivo

O aplicativo acessa o Supabase **exclusivamente com a chave publicável**
(`db._cliente()`), que por definição vai para o navegador de qualquer
visitante. E **26 das 28 tabelas** do schema `public` têm políticas RLS
concedendo a `anon` **SELECT, INSERT, UPDATE e DELETE irrestritos**
(`using (true)` / `with check (true)`).

Na prática, a chave publicável **é** a chave de administração do banco.

| Severidade | Achado |
|---|---|
| **Crítica** | `usuarios` aberta a escrita anônima → **tomada de contas** |
| **Crítica** | `config_app` com `OPENAI_API_KEY` e `GOOGLE_API_KEY` em texto puro, legíveis e **alteráveis** por anônimo |
| **Alta** | `processos` e `revisoes` legíveis e **apagáveis** por anônimo |
| **Alta** | 22 outras tabelas (governança, conhecimento, pareceres, fatos) idem |
| Média | `config_orgaos`, `secretarias`, `tenants` alteráveis → identidade visual e isolamento por tenant manipuláveis |

Verificado por consulta a `pg_class`, `pg_policies` e
`has_table_privilege` na produção (`nxibohgoekphxblqtqku`) em
**14/08/2026** — somente leitura.

---

## 2. `usuarios`: possibilidade de comprometimento de contas

A migração `0004` criou, num mesmo laço, quatro políticas para
`usuarios`, `config_app` e `config_orgaos`. **Confirmado aplicado em
produção:**

| Tabela | Política | Comando | `USING` | `WITH CHECK` |
|---|---|---|---|---|
| `usuarios` | `anon_select` | SELECT | `true` | — |
| `usuarios` | `anon_insert` | INSERT | — | `true` |
| `usuarios` | `anon_update` | UPDATE | `true` | `true` |
| `usuarios` | `anon_delete` | DELETE | `true` | — |

`relrowsecurity = true`, `relforcerowsecurity = false`, e `anon` detém
os quatro privilégios de tabela.

A própria 0004 registra a preocupação — e para na metade:

> *"qualquer detentor da chave publishable pode ler estas tabelas; os
> hashes PBKDF2 (200k iterações, salt por usuário) mitigam exposição de
> senhas."*

**O raciocínio está incompleto.** PBKDF2 protege contra a *inversão* do
hash, não contra a sua *substituição*. Com `UPDATE` liberado, ninguém
precisa quebrar senha:

1. gera-se localmente `pbkdf2_sha256$200000$<salt>$<hash>` de uma senha
   escolhida — o formato está em `src/auth.py`, e o repositório é
   público;
2. `PATCH /rest/v1/usuarios?login=eq.<admin>` trocando `senha_hash`;
3. entra-se pela tela de login normal, como administrador.

Há caminhos ainda mais curtos: `INSERT` de usuário novo já com
`papel = 'admin'`, ou `UPDATE` de `papel` na própria conta. O `DELETE`
liberado permite apagar todas as contas.

**Trate como comprometimento possível de contas.** Não há evidência de
exploração — mas também não há como afirmar que não ocorreu: as
políticas não registram autoria e o app não mantém trilha de acesso. Na
etapa 1, revisar `usuarios` procurando conta desconhecida, `papel`
inesperado ou `criado_em` fora do padrão, e forçar a redefinição de
todas as senhas.

---

## 3. Por que a migração 0018 **não pode** ser aplicada agora

Renomeada para `0018_rls_config_app_e_processos.sql.NAO_APLICAR`.

**O app não tem caminho privilegiado.** `db._cliente()` cria o cliente
com a chave publicável (`SUPABASE_KEY`) e **toda** operação passa por
ele. A autenticação é própria — PBKDF2 contra a tabela `usuarios`
(`src/auth.py`) —, **não é Supabase Auth**: não há `auth.uid()`, não há
JWT de usuário, não há uso de `service_role` em nenhum ponto do código.

A 0018 revoga `anon` sobre `config_app` e ativa RLS sem políticas. Como
o app **é** `anon`, ele passaria a enxergar a tabela vazia. E
`config_app` não guarda apenas segredos:

| Leitura | Função | Efeito se `config_app` sumir |
|---|---|---|
| `db.obter_config("OPENAI_API_KEY")` | motor principal | **a geração para** |
| `db.obter_config("GOOGLE_API_KEY")` | fallback | sem fallback |
| `db.flag_ativa(nome)` → `flag_<nome>` | **todas** as feature flags | **todas caem para OFF, em silêncio** |

`flag_ativa` devolve `False` quando a chave não existe (default OFF por
projeto). Aplicar a 0018 hoje desligaria de uma vez `tela_progresso`,
`correcao_automatica`, `canonical_facts`, `knowledge_engine_active` e
`knowledge_engine_shadow` — sem erro visível, apenas com o produto
voltando ao comportamento antigo.

**Fechar o acesso e manter o app funcionando só coexistem depois da
etapa 4 (arquitetura).**

---

## 4. Um atalho legítimo: tirar os segredos do banco sem tocar no schema

`llm._ler_chave` já resolve nesta ordem:

```
db.obter_config(nome)  →  st.session_state  →  st.secrets  →  os.getenv
```

Ou seja: **basta gravar as chaves nos Secrets do Streamlit Cloud e
apagar as linhas correspondentes de `config_app`.** O app continua
funcionando pelo terceiro degrau da cadeia, e os segredos deixam de
existir no banco — sem migração, sem alteração de código, sem
indisponibilidade.

Não resolve `usuarios` nem a exposição dos processos, mas elimina hoje o
item mais grave da tabela de severidade.

---

## 5. Inventário de exposição (produção, 14/08/2026)

**Tabelas:** 28 no schema `public`; **26** com políticas `anon` de CRUD
irrestrito. As duas exceções são exatamente os backups fechados pelas
migrações 0015/0016 — hoje os objetos mais protegidos do banco.

| Grupo | Tabelas | anon |
|---|---|---|
| Identidade e segredos | `usuarios`, `config_app`, `config_orgaos` | CRUD |
| Processos | `processos`, `revisoes`, `geracoes`, `decisoes`, `simulacoes`, `qualidade_scores` | CRUD |
| Conhecimento | `chunks_referencia`, `documentos_referencia`, `fontes_conhecimento`, `regras_conhecimento`, `fatos_canonicos` | CRUD |
| Governança | `governanca_artefatos`, `governanca_versoes`, `governanca_publicacoes`, `governanca_aprovacoes`, `governanca_eventos` | CRUD |
| Pareceres e melhoria | `pareceres`, `parecer_achados`, `melhoria_clusters`, `melhoria_propostas`, `aprendizado_feedback` | CRUD |
| Multi-tenant | `tenants`, `secretarias` | CRUD |
| Backups | `chunks_referencia_bkp_20260811`, `documentos_referencia_bkp_20260811` | **nenhum privilégio** ✅ |

Nota: `governanca_eventos` é tratada no código como trilha
*append-only*; com `UPDATE`/`DELETE` liberados a `anon`, essa
característica **não é garantida pelo banco**.

**Views:** nenhuma no schema `public`.

**Funções:** duas do domínio (`buscar_chunks_textual`,
`buscar_chunks_vetorial`) executáveis por `anon`, ambas `SECURITY
INVOKER` — herdam o RLS do chamador, sem escalação de privilégio.
`set_atualizado_em` está fechada. As demais são operadores do
`pgvector`. **Nenhuma função `SECURITY DEFINER` exposta** — é o único
ponto do inventário sem achado.

---

## 6. Plano de contenção e migração

### Etapa 1 — Rotação das chaves comprometidas
- Rotacionar `OPENAI_API_KEY` e `GOOGLE_API_KEY` nos provedores.
- Conferir o consumo nos painéis: uso fora do padrão indica exploração.
- Gravar as novas **nos Secrets do Streamlit**, não em `config_app`.
- Revisar `usuarios`: conta desconhecida, `papel` inesperado, `criado_em`
  atípico. Forçar redefinição de todas as senhas.
- *Pré-requisito de tudo: fechar o acesso não desfaz a exposição.*

### Etapa 2 — Contenção imediata do acesso anônimo
- Apagar de `config_app` as linhas de chave (seção 4) — o app segue
  pelos Secrets.
- Avaliar a rotação da própria chave publicável do Supabase.
- Decisão de risco a tomar: manter o app no ar durante as etapas 3–5 ou
  restringir o acesso. **Enquanto `usuarios` aceitar `UPDATE` anônimo, a
  tomada de conta continua possível.**

### Etapa 3 — Inventário completo de exposição
- Base na seção 5, reexecutada como script versionado (não consulta
  manual).
- Acrescentar `storage`, Edge Functions e objetos em outros schemas.
- Registrar quantas contas existem e quando foram criadas — linha de
  base para detectar inserções indevidas.

### Etapa 4 — Arquitetura de autenticação/autorização
Decisão de fundo; as migrações dependem dela.

- **Opção A — Supabase Auth.** Migrar `usuarios` para `auth.users`, RLS
  por `auth.uid()`, papéis por custom claims. Maior esforço; elimina a
  classe inteira do problema.
- **Opção B — manter a auth própria e mover o privilégio para o
  servidor.** Operações sensíveis (ler `config_app`, autenticar, gravar
  processo) passam a usar `service_role` no lado servidor; `anon` fica
  só com o que for público. Menor esforço; exige separar cliente e
  servidor com disciplina — hoje a mesma função atende os dois.
- **Opção C — RLS por tenant com JWT próprio assinado.** O app emite JWT
  com `tenant_id`/`papel` e as políticas leem
  `current_setting('request.jwt.claims')`.

Recomendo **A**, com **B** como transição: o app já tem o conceito de
tenant, e a auth própria concentra em `usuarios` um risco que o Supabase
Auth resolve de fábrica.

### Etapa 5 — Migrações de RLS e grants
Depois da etapa 4, nesta ordem:
1. `usuarios`: remover as políticas anônimas; leitura só do próprio
   registro; escrita só por caminho privilegiado.
2. `config_app`: a `0018` (renomear de volta para `.sql`), já sem
   segredos dentro.
3. `processos`/`revisoes`: RLS por `tenant_id`/`usuario_id`.
4. Conhecimento e governança: leitura autenticada, escrita só de admin.
5. `governanca_eventos`: negar `UPDATE`/`DELETE` a todos os papéis,
   tornando o append-only real.

### Etapa 6 — Testes de perfil
Executar **antes e depois** de cada migração, em ambiente de teste:

| Perfil | Deve conseguir | Deve ser negado |
|---|---|---|
| **Visitante** (só a chave publicável) | nada além do conteúdo público | ler `config_app`; ler ou alterar `usuarios`; ler processo alheio |
| **Usuário legítimo** | criar e editar os **próprios** processos; gerar e exportar | ver processo de outro tenant; alterar o próprio `papel`; ler segredos |
| **Usuário de outro tenant** | operar no tenant dele | qualquer leitura ou escrita cruzada |
| **Administrador** | gerir usuários, flags e catálogo do **seu** tenant | ler segredo em texto puro pela API pública |

Cada linha vira teste automatizado, contra um projeto de teste — nunca
contra produção.

### Etapa 7 — Aplicação e rollback
- Ambiente de teste com cópia do schema (sem dados reais) primeiro.
- Uma migração por vez, com a etapa 6 entre elas.
- Janela de baixo uso; comunicar os servidores.
- **Rollback:** cada migração acompanhada do SQL inverso (recriar as
  políticas anteriores). O caminho de volta é sempre recriar política,
  nunca restaurar dado — nenhuma dessas migrações toca em linhas.
- Critério de parada: se o app quebrar num passo, reverter **aquele**
  passo e reavaliar a etapa 4 antes de seguir.

---

## 7. O que este documento **não** faz

- Não aplica SQL.
- Não rotaciona chaves.
- Não altera produção.
- Não expõe valor de credencial: nenhuma chave, token ou hash foi
  copiado para este documento, para os commits ou para o transcript.
