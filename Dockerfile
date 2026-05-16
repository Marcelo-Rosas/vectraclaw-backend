# syntax=docker/dockerfile:1
# ── Stage 1: dependências + Playwright browsers ─────────────────────────────
FROM python:3.11-slim AS deps

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

    WORKDIR /app

    # Dependências de sistema para Playwright, pdfplumber, pandas, cryptography
    RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc \
            libpq-dev \
                curl \
                    libglib2.0-0 \
                        libnss3 \
                            libnspr4 \
                                libdbus-1-3 \
                                    libatk1.0-0 \
                                        libatk-bridge2.0-0 \
                                            libcups2 \
                                                libdrm2 \
                                                    libxkbcommon0 \
                                                        libxcomposite1 \
                                                            libxdamage1 \
                                                                libxfixes3 \
                                                                    libxrandr2 \
                                                                        libgbm1 \
                                                                            libasound2 \
                                                                                && rm -rf /var/lib/apt/lists/*

                                                                                COPY requirements.txt .
                                                                                RUN pip install --no-cache-dir -r requirements.txt

                                                                                # Instala apenas Chromium (evita Firefox + WebKit ~800MB extras)
                                                                                RUN playwright install chromium

                                                                                # ── Stage 2: imagem final ────────────────────────────────────────────────────
                                                                                FROM python:3.11-slim AS final

                                                                                ENV PYTHONDONTWRITEBYTECODE=1 \
                                                                                    PYTHONUNBUFFERED=1 \
                                                                                        PORT=3000

                                                                                        # Runtime libs mínimas para Playwright
                                                                                        RUN apt-get update && apt-get install -y --no-install-recommends \
                                                                                            curl \
                                                                                                libglib2.0-0 \
                                                                                                    libnss3 \
                                                                                                        libnspr4 \
                                                                                                            libdbus-1-3 \
                                                                                                                libatk1.0-0 \
                                                                                                                    libatk-bridge2.0-0 \
                                                                                                                        libcups2 \
                                                                                                                            libdrm2 \
                                                                                                                                libxkbcommon0 \
                                                                                                                                    libxcomposite1 \
                                                                                                                                        libxdamage1 \
                                                                                                                                            libxfixes3 \
                                                                                                                                                libxrandr2 \
                                                                                                                                                    libgbm1 \
                                                                                                                                                        libasound2 \
                                                                                                                                                            && rm -rf /var/lib/apt/lists/*
                                                                                                                                                            
                                                                                                                                                            WORKDIR /app
                                                                                                                                                            
                                                                                                                                                            # Copia site-packages e binários do stage de deps
                                                                                                                                                            COPY --from=deps /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
                                                                                                                                                            COPY --from=deps /usr/local/bin /usr/local/bin
                                                                                                                                                            # Copia browsers do Playwright (~180MB só Chromium)
                                                                                                                                                            COPY --from=deps /root/.cache/ms-playwright /root/.cache/ms-playwright
                                                                                                                                                            
                                                                                                                                                            # Copia código-fonte
                                                                                                                                                            COPY . .
                                                                                                                                                            
                                                                                                                                                            EXPOSE 3000
                                                                                                                                                            
                                                                                                                                                            # Entrypoint padrão: API (sobrescrito pelo serviço daemon no Compose)
                                                                                                                                                            CMD ["python", "-m", "src.main", "serve", "--port", "3000"]a código-fonte
                                                                                                                                                            COPY . .
                                                                                                                                                            
                                                                                                                                                            EXPOSE 3000
                                                                                                                                                            
                                                                                                                                                            # Entrypoint padrão: API (sobrescrito pelo serviço daemon no Compose)
                                                                                                                                                            CMD ["python", "-m", "src.main", "serve", "--port", "3000"]
