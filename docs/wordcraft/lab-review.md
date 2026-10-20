# Revisão do lifecycle do laboratório WordCraft

Decisão e uso registrados antes do código: corrigir somente os helpers existentes `subir_postgrest` e `subir_adaptador`, em `scripts/homologacao_stack.py`, para que o próprio helper encerre seu filho caso a espera inicial pela porta falhe. O laboratório e a pilha canônica reutilizam esses helpers; nenhum novo supervisor ou fluxo de processos será criado.

Problema observado em revisão somente leitura: `Popen` retorna um filho, mas `_esperar_porta` pode lançar antes de o helper retornar. O chamador normalmente registra o processo com `processes.append(helper(...))`; nesse intervalo, sua lista ainda está vazia e o `finally` do chamador não consegue encerrar o filho. Uma reprodução com `Popen` e espera simulados confirmou esse caminho, sem iniciar processo ou conectar ao banco.

Escopo deste incremento:

| Arquivo | Uso |
|---|---|
| `scripts/homologacao_stack.py` | Nos dois helpers, capturar `BaseException` durante `_esperar_porta`, chamar o `_encerrar` existente para o filho recém-criado e propagar a falha. Sucesso continua retornando o processo vivo ao chamador. |
| `tests/test_homologacao_stack_lifecycle.py` | Testar falha, interrupção e saída durante startup dos dois helpers; sucesso não encerra o filho; binário ausente e porta ocupada não iniciam processos. Todos os filhos e sondas são simulados. |
| `docs/wordcraft/lab-review.md` | Registrar causa, decisão, limites e resultado dos testes. |

Não altera DSN, SQL, banco, credenciais, ambiente do laboratório, app, ACK ou rotas públicas. A revisão apontou outros achados nesses caminhos, cuja correção pertence ao integrador. A rotina `_encerrar` existente permanece responsável por `SIGTERM`, espera e eventual `kill`; este incremento não redefine a semântica de shutdown da pilha inteira.

Verificação executada: antes da correção, os seis cenários `ErroPilha`, `KeyboardInterrupt` e `SystemExit`, nos dois helpers, falharam porque o filho simulado não recebeu `SIGTERM`; os outros cinco casos passaram. Depois da correção, **11 testes passaram** em 0,23 s. Os testes de erro usam o `_encerrar` real sobre um objeto de processo simulado e conferem sinal, espera e propagação da mesma exceção original. Nenhum `Popen`, sonda de socket ou acesso a banco real ocorreu. `git diff --check` não apontou erros nos arquivos deste incremento.
