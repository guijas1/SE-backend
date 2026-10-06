"""SmartAir telemetry API."""

from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Query

from smartair import database
from smartair.schemas import TelemetryInput, alerta_geral


database.inicializar()
app = FastAPI(title="SmartAir API", version="1.1.0")


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/dados")
def receber_dados(leitura: TelemetryInput) -> dict[str, int | str]:
    payload = leitura.model_dump()
    payload["alerta_geral"] = alerta_geral(leitura)
    criado_em = datetime.now(timezone.utc).isoformat(timespec="seconds")
    leitura_id = database.salvar(payload, criado_em)
    return {"status": "ok", "id": leitura_id}


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
