FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    NODE_VERSION=22.22.2

# ============================================================
# SYSTEM DEPENDENCIES
# ============================================================

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ffmpeg \
        curl \
        ca-certificates \
        xz-utils \
        git \
        build-essential \
    && rm -rf /var/lib/apt/lists/*


# ============================================================
# NODE.JS
# Required by yt-dlp JavaScript/EJS runtime
# ============================================================

RUN curl -fsSL \
    "https://nodejs.org/dist/v${NODE_VERSION}/node-v${NODE_VERSION}-linux-x64.tar.xz" \
    | tar -xJ \
        --strip-components=1 \
        -C /usr/local \
    && node --version \
    && npm --version


# ============================================================
# BGUTIL PO-TOKEN PROVIDER
# ============================================================

RUN git clone \
    --depth 1 \
    --branch 2.0.0 \
    https://github.com/Brainicism/bgutil-ytdlp-pot-provider.git \
    /opt/bgutil \
    && cd /opt/bgutil/server \
    && npm ci \
    && npx tsc


# ============================================================
# APPLICATION
# ============================================================

WORKDIR /app


# Python dependencies
COPY requirements.txt .

RUN python -m pip install --upgrade pip \
    && python -m pip install -r requirements.txt


# Application files
COPY main.py .
COPY start.sh .


# YouTube cookies
# IMPORTANT: cookie.txt must exist in the GitHub repository
COPY cookie.txt /app/cookie.txt


# Make start script executable
RUN chmod +x /app/start.sh


# ============================================================
# PORT
# ============================================================

EXPOSE 8000


# ============================================================
# START
# ============================================================

CMD ["/app/start.sh"]
