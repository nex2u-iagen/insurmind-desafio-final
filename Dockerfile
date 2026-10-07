FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/home/seguramente/.cache/huggingface \
    SEGURAMENTE_LOG_LEVEL=INFO \
    SEGURAMENTE_DATA_DIR=/var/lib/seguramente \
    SEGURAMENTE_ENV_FILE=/var/lib/seguramente/.env \
    TQDM_DISABLE=1 \
    HF_HUB_DISABLE_PROGRESS_BARS=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libgomp1 \
        poppler-utils \
        tesseract-ocr \
        tesseract-ocr-eng \
        tesseract-ocr-por \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./requirements.txt
RUN python -m pip install --upgrade pip \
    && python -m pip install -r requirements.txt

RUN groupadd --system --gid 10001 seguramente \
    && useradd --system --uid 10001 --gid seguramente \
        --home-dir /home/seguramente --create-home \
        --shell /usr/sbin/nologin seguramente

COPY --chown=seguramente:seguramente app.py ./app.py
COPY --chown=seguramente:seguramente seguramente_final ./seguramente_final
COPY --chown=seguramente:seguramente data/policies/Apolice_DO_A.pdf ./data/policies/Apolice_DO_A.pdf
COPY --chown=seguramente:seguramente data/policies/Apolice_DO_B.pdf ./data/policies/Apolice_DO_B.pdf

RUN mkdir -p /var/lib/seguramente /home/seguramente/.cache/epochdb_models /home/seguramente/.cache/huggingface \
    && chown -R seguramente:seguramente /var/lib/seguramente /home/seguramente

USER seguramente

EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health', timeout=4)" || exit 1

CMD ["python", "-m", "streamlit", "run", "app.py", "--server.address=0.0.0.0", "--server.port=8501", "--server.fileWatcherType=none"]
