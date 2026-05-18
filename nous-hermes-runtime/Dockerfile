# Nous Hermes runtime — hermes-agent CLI + HTTP wrapper (PRD F1)
# Debian 13 (trixie): menos CVEs HIGH que bookworm no scan Docker DX/Scout.
# Docker DX avisa 3× HIGH na linha FROM (glibc + wheel embutidos na imagem oficial);
# os RUNs abaixo corrigem no build — valide com: docker scout cves <sua-imagem> --only-severity high
FROM python:3.11-slim-trixie

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HERMES_HOME=/root/.hermes \
    PATH="/root/.local/bin:${PATH}"

# nodejs/npm: install.sh exige Node mesmo com --skip-browser (só pula Playwright).
# xz-utils: fallback se o script tentar extrair node-v*.tar.xz manualmente.
# upgrade: aplica correções de segurança do repositório (ex.: glibc, dpkg) no build.
RUN apt-get update \
    && apt-get upgrade -y \
    && apt-get install -y --no-install-recommends \
    git \
    curl \
    ca-certificates \
    ripgrep \
    ffmpeg \
    xz-utils \
    nodejs \
    npm \
    && rm -rf /var/lib/apt/lists/*

# CVE-2026-24049: wheel<=0.46.1 (incl. cópia em setuptools/_vendor); glibc: deb13u3 via apt upgrade.
RUN pip install --no-cache-dir --upgrade \
    'pip>=24' \
    'wheel>=0.46.2' \
    'setuptools>=82'

# uv (usado pelo install.sh upstream)
RUN curl -LsSf https://astral.sh/uv/install.sh | sh

WORKDIR /opt
RUN git clone --depth 1 --branch main https://github.com/NousResearch/hermes-agent.git hermes-agent

WORKDIR /opt/hermes-agent
RUN bash scripts/install.sh --skip-setup --skip-browser

COPY requirements.txt /tmp/nous-hermes-requirements.txt
RUN pip install --no-cache-dir -r /tmp/nous-hermes-requirements.txt

WORKDIR /app
COPY wrapper.py entrypoint.sh ./
RUN sed -i 's/\r$//' entrypoint.sh && chmod +x entrypoint.sh

EXPOSE 9120

HEALTHCHECK --interval=30s --timeout=10s --start-period=120s --retries=3 \
    CMD curl -f http://localhost:9120/health || exit 1

ENTRYPOINT ["./entrypoint.sh"]
