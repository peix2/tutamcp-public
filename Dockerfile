# Etap 1: pobierz pakiet tuta/ z tutaproxy-public (tylko do buildu)
FROM python:3.11-slim AS builder

ARG TUTAPROXY_REF=v1.3.13

RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

RUN git clone --depth 1 --branch ${TUTAPROXY_REF} \
    https://github.com/peix2/tutaproxy-public.git /build/tutaproxy-public

# Etap 2: obraz runtime — bez gita
FROM python:3.11-slim

WORKDIR /app

# Skopiuj pakiet tuta/ z buildera (klient API Tuty)
COPY --from=builder /build/tutaproxy-public/tuta ./tuta

# Zainstaluj zależności
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Skopiuj kod tutamcp
COPY server.py .
COPY tutamcp/ ./tutamcp/

# Domyślny katalog na pobierane pliki (można nadpisać przez -e)
ENV TUTAMCP_DOWNLOAD_DIR=/tmp/tutamcp

# Credentials montuj jako volume lub ustaw TUTAMCP_CREDENTIALS_FILE:
#   docker run -v /host/path/credentials.env:/creds.env \
#              -e TUTAMCP_CREDENTIALS_FILE=/creds.env ...
# Albo przekaż TUTA_EMAIL i TUTA_PASSWORD bezpośrednio przez -e.

# MCP używa stdio — brak portu do eksponowania
CMD ["python", "server.py"]
