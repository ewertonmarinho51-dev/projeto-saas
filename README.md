# 🏛️ GovDocs Wizard — Fase Preparatória (Lei nº 14.133/2021)

Aplicação web em **Python + Streamlit** que automatiza, em formato de
assistente passo a passo (*wizard*), a elaboração dos 4 documentos
essenciais da fase preparatória das licitações públicas:

1. **DFD** — Documento de Formalização da Demanda (art. 12, VII)
2. **ETP** — Estudo Técnico Preliminar (art. 18, §1º)
3. **TR** — Termo de Referência (art. 6º, XXIII, e art. 40)
4. **Minuta de Edital / Ata de Registro de Preços** (art. 25)

A redação é feita pela IA (**Google Gemini**) com *system prompts*
rigorosos e **encadeamento sequencial de contexto**: cada documento usa o
anterior — já revisado e aprovado pelo usuário — como fundamento. Nada
avança sem aprovação humana (tela de *preview* editável em cada etapa).

## ✨ Funcionalidades

- **Formulário Matriz** com tooltips (❓) explicando o que a Lei
  14.133/2021 espera de cada informação.
- **Wizard de 6 passos** com indicador visual de progresso — o usuário
  nunca é sobrecarregado com mais de uma decisão por tela.
- **Preview editável** de cada documento antes da aprovação (controle
  humano garantido) + botão "Gerar novamente".
- **Invalidação em cascata**: se você volta e altera um documento (ou o
  formulário), os documentos seguintes são descartados e regenerados.
- **Exportação**: dossiê completo em **PDF** e **DOCX** (arquivo único)
  ou pacote **.zip** com os 4 arquivos individuais.
- **Tratamento de erros amigável**: timeout, chave inválida, cota
  excedida e bloqueio de conteúdo geram mensagens claras, com
  retentativas automáticas (backoff exponencial) — os dados nunca se perdem.
- **Modo Demonstração** (offline, sem chave de API) para conhecer o fluxo.

## 📁 Estrutura de pastas

```
projeto-saas/
├── app.py                        # Ponto de entrada — roteamento do wizard
├── requirements.txt              # Dependências Python
├── README.md
├── .gitignore                    # Protege .streamlit/secrets.toml
├── .streamlit/
│   ├── config.toml               # Tema visual corporativo (azul institucional)
│   └── secrets.toml.example      # Modelo p/ configurar a chave da API
└── src/
    ├── __init__.py
    ├── config.py                 # Etapas, documentos e campos do formulário (c/ tooltips)
    ├── prompts.py                # System prompts rigorosos por documento
    ├── llm.py                    # Cliente Gemini: retry, timeout, erros amigáveis, modo demo
    ├── state.py                  # Estado do wizard (st.session_state)
    ├── export.py                 # Conversão Markdown ➜ .docx / .pdf / .zip
    └── ui/
        ├── __init__.py
        ├── components.py         # CSS, cabeçalho, stepper, barra lateral
        └── steps.py              # Telas: formulário, preview/edição, sucesso
```

## 🚀 Como rodar localmente

```bash
# 1. Clonar e entrar no projeto
git clone https://github.com/ewertonmarinho51-dev/projeto-saas.git
cd projeto-saas

# 2. Ambiente virtual (recomendado)
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# 3. Dependências
pip install -r requirements.txt

# 4. Chave da API (Google AI Studio — https://aistudio.google.com/apikey)
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
#    ➜ edite o arquivo e cole sua chave em GOOGLE_API_KEY
#    (alternativas: export GOOGLE_API_KEY="sua-chave" ou colar na barra lateral)

# 5. Executar
streamlit run app.py             # abre em http://localhost:8501
```

> 💡 **Sem chave de API?** Ative o *Modo Demonstração* na barra lateral
> para percorrer o fluxo completo com minutas-esqueleto geradas offline.

## 🔄 Fluxo de funcionamento

```
Passo 1            Passo 2         Passo 3         Passo 4         Passo 5
Formulário   ➜     DFD       ➜     ETP       ➜     TR        ➜     Edital/Ata  ➜  📦 Download
Matriz             (art.12)        (art.18)        (art.40)        (art.25)       PDF · DOCX · ZIP
                   ↑ preview       ↑ preview       ↑ preview       ↑ preview
                   editável        editável        editável        editável
                   + aprovação     + aprovação     + aprovação     + aprovação
```

Contexto enviado à IA em cada etapa:

| Documento | Contexto usado |
|---|---|
| DFD | Formulário Matriz |
| ETP | Formulário + **DFD aprovado** |
| TR | Formulário + **ETP aprovado** (contexto exclusivo das definições técnicas) |
| Edital/Ata | Formulário + **TR aprovado** |

## ⚠️ Aviso legal

Os textos gerados são **rascunhos de apoio** à equipe de planejamento da
contratação. Eles **não substituem** a análise técnica e jurídica exigida
pela Lei nº 14.133/2021 (parecer jurídico — art. 53 — e demais controles).
Revise todo o conteúdo antes do uso oficial.
