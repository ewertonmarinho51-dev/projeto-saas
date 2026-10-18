# C11 — aceite de imutabilidade de aprovado e emitido

Data: 18/10/2026  
Escopo: PostgreSQL 16 local descartável, migrations completas e RPCs reais  
Estado: **PASS SQL LOCAL; sessão JWT/PostgREST e fluxo visual ainda pendentes**

O manifesto offline continua `NOT_TESTED`: seus dois arquivos são sementes e
não podem declarar que o banco executou o fluxo. A prova funcional está no teste
`test_c11_approved_and_emitted_head_never_rewrites_historical_revision`.

| Campo | Evidência |
|---|---|
| ID | C11-SQL-01 |
| Fixture | revisão 1 com `C11-LEGACY-ORIGINAL`; tentativa posterior com `C11-REVISION-NEW` |
| Ambiente | PostgreSQL 16 local descartável; schema integral; papel `service_role` com claims sintéticos autenticados; sem remoto ou produção |
| Ações | criar revisão 1; aprovar pelo ato canônico; tentar checkpoint da revisão nova; conferir histórico; marcar o mesmo head como emitido; repetir tentativa; conferir revisão, hash e vínculo da aprovação |
| Esperado | aprovado e emitido recusam escrita; revisão 1 permanece byte-idêntica; head não avança; aprovação continua vinculada à revisão/hash originais |
| Observado | ambas as tentativas retornam `InsufficientPrivilege`; existe somente a revisão 1; bytes e SHA-256 originais permanecem; head continua na revisão 1; vínculo aprovado aponta a revisão/hash originais |
| Resultado | PASS SQL LOCAL |
| Regressão | `tests/test_documentos_editor_aprovacao_sql.py` |

O teste não cria uma “revisão 2” dentro de um ato aprovado. O contrato atual
fecha o head aprovado/emitido; uma futura edição institucional deve iniciar um
novo fluxo explicitamente autorizado, sem alterar a revisão ou aprovação
históricas. Inventar esse fluxo dentro do teste esconderia uma lacuna de produto.

Ainda faltam a mesma prova pelo transporte PostgREST com JWT GoTrue real e a
observação no navegador de que a UI não oferece autosave/edição sobre o head
fechado. Esses limites impedem promover C11 a aceite end-to-end ou encerrar G7.
