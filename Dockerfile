FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TZ=America/Sao_Paulo \
    PYTHONPATH=/app/api

WORKDIR /app

RUN groupadd --system --gid 10001 smartair \
    && useradd --system --uid 10001 --gid smartair --home-dir /app smartair \
    && mkdir -p /data \
    && chown smartair:smartair /app /data

COPY requirements.txt ./requirements.txt
COPY api/requirements.txt ./api/requirements.txt
COPY dashboard/requirements.txt ./dashboard/requirements.txt
RUN python -m pip install --no-cache-dir -r requirements.txt

COPY --chown=smartair:smartair api/smartair ./api/smartair
COPY --chown=smartair:smartair dashboard ./dashboard

USER smartair

EXPOSE 8080 8501

CMD ["python", "-m", "uvicorn", "smartair.main:app", "--host", "0.0.0.0", "--port", "8080"]
