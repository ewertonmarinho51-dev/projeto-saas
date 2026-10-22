# Skills/plugins para Claude Code — verificados nos READMEs oficiais
**Regra:** não instalar tudo indiscriminadamente. Para cada skill: verificar origem, README e comandos na revisão atual, hooks, scripts e permissões. Pedir aprovação humana para instalação ou execução externa. Nada de `curl|bash` às cegas. Skills não substituem implementação.

| Ferramenta | O que realmente faz | Decisão no Gov Conect | Fonte |
|---|---|---|---|
| `design-taste`, `design-minimalist`, `design-motion-principles` | skills já existentes no `.claude/skills/` do projeto | **Obrigatórias e primeiro recurso** | repo próprio |
| `caveman` | comunicação concisa no Claude | manter | repo próprio |
| Cartographer | mapa semântico de arquivos/símbolos já instalado | **Primeiro mapa**; graphify só se lacuna comprovada | `.mcp.json` e `CLAUDE.md` atuais |
| Anthropic plugins official | marketplace curado de plugins Claude; não é uma skill única | consultar diretório quando faltar recurso; plugins 1–2/categoria | https://github.com/anthropics/claude-plugins-official |
| `diagram-design` | HTML/SVG editorial, componentes de diagramas | **Instalar para fluxos da landing**, sem diagramas fake | https://github.com/cathrynlavery/diagram-design |
| `motionmaxxing` | roteirizar/gerar/analisar motion graphics localmente como MP4 | **Opcional só após hero/login estáticos prontos** | https://github.com/Tejashmakwana/motionmaxxing |
| `@playwright/cli` | automação browser CLI + skills, screenshots, interações | **Essencial para QA visual/E2E** | https://github.com/microsoft/playwright-cli |
| `addyosmani/agent-skills` | workflows de spec→plan→build→test→review→ship | instalar poucas skills úteis ou plugin; usar frontend-ui, API, CI, security | https://github.com/addyosmani/agent-skills |
| `Graphify-Labs/graphify` | gera knowledge graph/consulta de código e documentos | **Opcional, duplicado ao Cartographer**; não instalar por padrão | https://github.com/Graphify-Labs/graphify |
| `DietrichGebert/ponytail` | disciplina YAGNI/menor mudança funcional com hooks | opcional; revisar hooks antes, pode ser útil | https://github.com/DietrichGebert/ponytail |
| `Trail of Bits/insecure-defaults` | auditoria de defaults inseguro/fail-open | **Essencial no hardening**, além de SAST e auth/RLS tests | https://github.com/trailofbits/skills/tree/main/plugins/insecure-defaults |

## Instalação — comandos documentados, não rodados aqui
```text
# Dentro do Claude Code, em comandos separados, APÓS revisar o repo:
/plugin marketplace add cathrynlavery/diagram-design
/plugin install diagram-design@diagram-design
/plugin marketplace add addyosmani/agent-skills
/plugin install agent-skills@addy-agent-skills
/plugin marketplace add DietrichGebert/ponytail
/plugin install ponytail@ponytail

# No terminal local, após revisão e confirmação de ambiente:
npm install -g @playwright/cli@latest
playwright-cli install --skills

# motionmaxxing: requer Node 22+, Python 3, ffmpeg, Chrome.
# Procedimento Git / install.sh segue o README; testar dependências e segurança
# antes de permitir a instalação. Não executar como root.

# Codex CLI (se instalado e autorizado), auditoria ToB:
codex plugin marketplace add trailofbits/skills
codex plugin add insecure-defaults@trailofbits
# no chat do Codex: /insecure-defaults:audit src/
```

## Graphify
O README indica `pip install graphifyy && graphify install` e `/graphify .`. Só usar se o Cartographer não oferecer uma visão importante; proibir hooks automáticos sem consentimento. Prioridade desempenho/contexto > acúmulo de plugins.

## Ferramentas de terceiros adicionais
- `sindresorhus/awesome`/`punkpeye/awesome-mcp-servers` são **catálogos**, não dependências.
- `D4Vinci/Scrapling` NÃO autoriza contornar Cloudflare, contratos ou regras de coleta; não usar técnicas evasivas no módulo de pesquisa. Preferir APIs públicas/licenciadas e conformidade das fontes.
- `ollama` pode rodar modelos locais, mas GPU/RAM/custo e homologação documental tornam-no inadequado como dependência crítica no VPS inicial.
- `langflow`, `OpenHands`, `open-design`, `awesome-llm-apps` podem inspirar protótipos, mas não entram no runtime nem no CI por padrão.
- Nunca copiar código/licença de repositórios sem revisar segurança, licença e manutenção.
