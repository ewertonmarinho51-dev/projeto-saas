# ###########################################################
#  GovDocs — imagem de produção para VPS próprio
#
#  Substitui o Streamlit Cloud, que instalava `requirements.txt`
#  e `packages.txt` por conta própria. Aqui isso é explícito:
#  o que o Cloud fazia por convenção, esta imagem faz por
#  instrução, e é a mesma imagem que roda na sua máquina.
# ###########################################################

FROM python:3.11-slim-bookworm

# ---------------------------------------------------------------
# DEPENDÊNCIAS DE SISTEMA
#
# `libreoffice-writer` é o que `packages.txt` pedia como
# `libreoffice` — e a diferença importa. O ensaio local desta
# suíte falhava em `test_os_210_codigos_saem_uma_unica_vez_no_pdf
# [libreoffice]` justamente porque o binário `soffice` existia
# sem o pacote do Writer, e a conversão caía no fallback `fpdf2`
# sem avisar. Aqui o pacote é nomeado, e o PDF institucional sai
# pelo motor certo.
#
# `--no-install-recommends` evita arrastar o ambiente gráfico
# inteiro; `fonts-dejavu` entra porque LibreOffice sem fonte
# renderiza caixas no lugar de acentos, e documento público com
# "JUSTIFICATIVA" virando "JUSTIFICATIVA" quebrado é defeito que
# só aparece no PDF final.
# ---------------------------------------------------------------
RUN apt-get update && apt-get install -y --no-install-recommends \
        libreoffice-writer \
        fonts-dejavu \
        curl \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# ---------------------------------------------------------------
# USUÁRIO SEM PRIVILÉGIO
#
# O contentor não roda como root. Se o processo for comprometido,
# quem estiver dentro não é dono do sistema de arquivos da imagem.
# ---------------------------------------------------------------
RUN useradd --create-home --uid 10001 govdocs

WORKDIR /app

# Dependências antes do código: a camada de `pip install` só é
# refeita quando `requirements.txt` muda, e não a cada commit.
COPY requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

COPY --chown=govdocs:govdocs app.py ./
COPY --chown=govdocs:govdocs src/ ./src/
COPY --chown=govdocs:govdocs assets/ ./assets/
COPY --chown=govdocs:govdocs .streamlit/config.toml ./.streamlit/config.toml

# `scripts/` e `supabase/` NÃO entram na imagem: são ferramentas de
# desenvolvimento e migrações que se aplicam pelo painel do
# Supabase. Imagem de produção que carrega migração é imagem que
# um dia aplica migração sozinha.

USER govdocs

EXPOSE 8501

# O healthcheck usa o endpoint que o próprio Streamlit expõe. Sem
# ele, o Docker dá o contentor por saudável enquanto o processo
# subiu e o app não responde — e o Caddy passaria a mandar tráfego
# para uma porta muda.
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD curl -fsS http://localhost:8501/_stcore/health || exit 1

# `address 0.0.0.0` porque o Caddy fala com o contentor pela rede
# interna do compose. A porta NÃO é publicada no host (ver o
# compose): quem fala com a internet é o Caddy, e só ele.
CMD ["streamlit", "run", "app.py", \
     "--server.port=8501", \
     "--server.address=0.0.0.0", \
     "--server.headless=true", \
     "--browser.gatherUsageStats=false"]
