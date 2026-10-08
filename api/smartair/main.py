"""SmartAir telemetry API."""

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Query, Request

from smartair import database
from smartair.notifications import NotificationConfig, NotificationService
from smartair.schemas import TelemetryInput, alerta_geral


@asynccontextmanager
async def lifespan(app: FastAPI):
    database.inicializar()
    servico = NotificationService(NotificationConfig.from_env())
    app.state.notifications = servico
    parar = asyncio.Event()
    tarefa = asyncio.create_task(servico.executar(parar)) if servico.config.enabled else None
    try:
        yield
    finally:
        parar.set()
        if tarefa:
            await tarefa


app = FastAPI(title="SmartAir API", version="1.2.0", lifespan=lifespan)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/dados")
def receber_dados(leitura: TelemetryInput, request: Request) -> dict[str, int | str]:
    payload = leitura.model_dump()
    payload["alerta_geral"] = alerta_geral(leitura)
    criado_em = datetime.now(timezone.utc).isoformat(timespec="seconds")
    leitura_id = request.app.state.notifications.registrar_leitura(payload, criado_em)
    return {"status": "ok", "id": leitura_id}


@app.get("/api/notificacoes/status")
def consultar_status_notificacoes(request: Request) -> dict:
    return request.app.state.notifications.status()


@app.get("/api/dados")
def consultar_ultima_leitura() -> dict:
    leitura = database.mais_recente()
    if leitura is None:
        raise HTTPException(status_code=404, detail="Nenhuma leitura recebida ainda")
    return leitura


@app.get("/api/dados/historico")
def consultar_historico(
    horas: int = Query(default=24, ge=1, le=720),
    limite: int = Query(default=1000, ge=1, le=5000),
) -> list[dict]:
    return database.historico(horas, limite)
