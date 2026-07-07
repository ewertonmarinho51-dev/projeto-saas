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
- **Banco de dados Supabase (PostgreSQL)**: cada processo é salvo
  automaticamente a cada etapa aprovada; o painel lateral "Processos
  Salvos" permite retomar ou excluir trabalhos anteriores de qualquer
  máquina. Sem credenciais configuradas, o app funciona normalmente
  (apenas sem persistência).
- **📚 Base de Conhecimento (RAG)**: envie leis, acórdãos, entendimentos
  dos Tribunais de Contas, processos anteriores e modelos (PDF/DOCX/
  TXT/MD). Os arquivos são divididos em trechos, indexados no Supabase
  com embeddings do Gemini (pgvector) e recuperados automaticamente na
  geração de cada documento para fundamentar a redação — com busca
  textual em português como fallback quando não há chave de API.

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
    ├── db.py                     # Persistência no Supabase (salvar/retomar processos)
    ├── rag.py                    # Base de Conhecimento: extração, chunks, embeddings, busca
    ├── state.py                  # Estado do wizard (st.session_state) + autosave
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

# 5. Banco de dados (Supabase) — opcional, para salvar/retomar processos
#    No mesmo .streamlit/secrets.toml, preencha:
#      SUPABASE_URL = "https://SEU-PROJETO.supabase.co"   (Settings ➜ API)
#      SUPABASE_KEY = "sb_publishable_..."                 (chave publishable/anon)

# 6. Executar
streamlit run app.py             # abre em http://localhost:8501
```

## 🗄️ Banco de dados (Supabase)

A tabela `public.processos` guarda o Formulário Matriz (`dados`), os
quatro documentos (`documentos`), as aprovações (`aprovados`) e a etapa
atual — um registro por processo, atualizado automaticamente a cada
avanço no wizard. Migração para criar a estrutura em um projeto novo:

```sql
create table public.processos (
  id uuid primary key default gen_random_uuid(),
  criado_em timestamptz not null default now(),
  atualizado_em timestamptz not null default now(),
  orgao text not null default '',
  objeto text not null default '',
  etapa int not null default 0,
  dados jsonb not null default '{}'::jsonb,
  documentos jsonb not null default '{}'::jsonb,
  aprovados text[] not null default '{}'
);
create index processos_atualizado_em_idx on public.processos (atualizado_em desc);

create or replace function public.set_atualizado_em()
returns trigger language plpgsql security invoker set search_path = ''
as $$ begin new.atualizado_em = now(); return new; end; $$;

revoke execute on function public.set_atualizado_em() from public, anon, authenticated;

create trigger trg_processos_atualizado
before update on public.processos
for each row execute function public.set_atualizado_em();

alter table public.processos enable row level security;
create policy "anon_select" on public.processos for select to anon using (true);
create policy "anon_insert" on public.processos for insert to anon with check (true);
create policy "anon_update" on public.processos for update to anon using (true) with check (true);
create policy "anon_delete" on public.processos for delete to anon using (true);
```

> ⚠️ As políticas acima liberam o papel `anon` (ferramenta interna de
> tenant único, chave publishable). Para uso multiusuário em produção,
> adicione **Supabase Auth** e restrinja as políticas por usuário
> (`auth.uid()`).

As migrações completas estão versionadas em `supabase/migrations/` —
incluindo `0003_base_conhecimento_rag.sql`, que cria as tabelas
`documentos_referencia` e `chunks_referencia` (pgvector + busca textual
em português) da Base de Conhecimento. Para aplicar manualmente, cole o
conteúdo no **SQL Editor** do painel Supabase.

## 📚 Base de Conhecimento (RAG)

Na página "Base de Conhecimento" (menu lateral), envie os materiais que
devem fundamentar a redação:

| Categoria | Exemplos | Como a IA usa |
|---|---|---|
| Lei / Norma | Lei 14.133/2021, IN SEGES, decretos locais | Citação expressa de dispositivos |
| Acórdão | Acórdãos TCU/TCE | Citação de precedentes pertinentes |
| Entendimento | Orientações e súmulas dos TCs | Fundamentação das escolhas |
| Processo anterior | DFDs, ETPs, TRs já realizados | Padrão de redação e estrutura |
| Modelo | Minutas-padrão (AGU etc.) | Estrutura de cláusulas |

Em cada geração, a aplicação monta uma consulta com o objeto/justificativa
do processo, recupera os trechos mais relevantes (busca vetorial
`gemini-embedding-001` + pgvector; fallback: full-text search em
português) e os injeta no prompt com a instrução de **não copiar dados
específicos de outros processos** — o formulário atual sempre prevalece.

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
