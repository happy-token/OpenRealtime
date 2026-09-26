FROM python:3.10.20-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg git util-linux bash ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 modelsvc

COPY deploy/inference_services/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY deploy/inference_services /app/deploy/inference_services
COPY scripts/wav2lip_provider.py scripts/liveportrait_provider.py scripts/liveportrait_retarget_image.py scripts/generate_musetalk_talking.sh /app/scripts/

RUN mkdir -p /data/jobs && chown -R modelsvc:modelsvc /data
USER modelsvc
EXPOSE 8000
HEALTHCHECK --interval=60s --timeout=190s --start-period=120s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=185)" || exit 1
CMD ["uvicorn", "deploy.inference_services.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
