# P05 — Gate F4: integrar editor do outro agente SEM reescrever
Antes de começar, confirme que o PR do outro agente responsável por `src/documentos_editor.py`/WordCraft, suas migrations e contracts está concluído ou pronto para integração. Capture SHA e diff. **Nunca** sobrescreva arquivos do outro agente.

Construa adapters FastAPI para criação, snapshots, patches, aprovação, auditoria, exportações e GovBot, baseando-se **nos contratos reais** dos módulos/migrations atuais, não em payload imaginado. Apresente editor na UI Next.js compatível com o runtime WordCraft já desenvolvido; caso integração browser real exija abordagem especial, documentar ADR e testar a fidelidade do documento. Preservar aprovação humana, herança DFD→ETP→TR, revisão e exportação institucional.

Testar guardar/reabrir, refresh, edições simultâneas/versão 409, DOCX/PDF mantendo texto e valores, export com 210 itens, recuperação após erro, isolamento tenant, auditoria e WordCraft suite. Se contratos instáveis: manter UI feature flag off e declarar BLOCKED; continuar etapas independentes de observabilidade e CI.
