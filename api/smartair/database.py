"""SQLite connection and backward-compatible schema initialization."""

import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


DATABASE_PATH = Path(
    os.getenv(
        "SMARTAIR_DATABASE_PATH",
        str(Path(__file__).resolve().parents[2] / "smartair.db"),
    )
).expanduser()

_COLUMNS = {
    "temperatura": "REAL",
    "umidade": "REAL",
    "mq135_adc": "INTEGER",
    "baseline_mq135": "INTEGER",
    "limite_mq_alerta": "INTEGER",
    "limite_mq_normal": "INTEGER",
    "estado_mq": "TEXT",
    "estado_sistema": "TEXT",
    "erro_dht": "INTEGER",
    "alerta_temperatura": "INTEGER",
    "alerta_umidade": "INTEGER",
    "alerta_qualidade_ar": "INTEGER",
    "alerta_geral": "INTEGER",
    "led_verde": "INTEGER",
    "led_vermelho": "INTEGER",
    "buzzer": "INTEGER",
    "buzzer_alerta": "INTEGER",
    "ventilacao_ligada": "INTEGER",
    "rele_ligado": "INTEGER",
    "rele_habilitado": "INTEGER",
    "motivos_alerta": "TEXT",
    "criado_em": "TEXT",
}


@contextmanager
def conectar() -> Iterator[sqlite3.Connection]:
    banco = sqlite3.connect(DATABASE_PATH, timeout=10)
    banco.row_factory = sqlite3.Row
    try:
        yield banco
        banco.commit()
    except Exception:
        banco.rollback()
        raise
    finally:
        banco.close()


def inicializar() -> None:
    """Create the telemetry table and add columns to an earlier MVP database."""
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with conectar() as banco:
        banco.execute(
            """CREATE TABLE IF NOT EXISTS leituras (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                temperatura REAL,
                umidade REAL,
                criado_em TEXT
            )"""
        )
        existing = {row["name"] for row in banco.execute("PRAGMA table_info(leituras)")}
        for name, sql_type in _COLUMNS.items():
            if name not in existing:
                banco.execute(f"ALTER TABLE leituras ADD COLUMN {name} {sql_type}")
        banco.execute(
            """CREATE TABLE IF NOT EXISTS notificacao_estado (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                dados TEXT NOT NULL
            )"""
        )
        banco.execute(
            """CREATE TABLE IF NOT EXISTS notificacoes (
                id TEXT PRIMARY KEY,
                payload TEXT NOT NULL,
                criado_em TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pendente',
                tentativas INTEGER NOT NULL DEFAULT 0,
                proxima_tentativa REAL NOT NULL DEFAULT 0,
                lease_token TEXT,
                lease_ate REAL NOT NULL DEFAULT 0,
                enviado_em TEXT,
                ultimo_erro TEXT
            )"""
        )
        banco.execute(
            """CREATE TABLE IF NOT EXISTS notificacao_alertas_enviados (
                campo TEXT PRIMARY KEY,
                enviado_em REAL NOT NULL
            )"""
        )
        banco.execute("CREATE INDEX IF NOT EXISTS notificacoes_envio ON notificacoes (enviado_em)")


def salvar(payload: dict, criado_em: str) -> int:
    with conectar() as banco:
        return inserir_leitura(banco, payload, criado_em)


def inserir_leitura(banco: sqlite3.Connection, payload: dict, criado_em: str) -> int:
    """Insert using the caller's transaction, including any notification events."""
    values = {**payload, "criado_em": criado_em}
    if values.get("motivos_alerta") is not None:
        values["motivos_alerta"] = json.dumps(values["motivos_alerta"], ensure_ascii=False)
    columns = list(_COLUMNS)
    placeholders = ", ".join("?" for _ in columns)
    query = f"INSERT INTO leituras ({', '.join(columns)}) VALUES ({placeholders})"
    cursor = banco.execute(query, [values.get(name) for name in columns])
    return int(cursor.lastrowid)


def _formatar(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    item = dict(row)
    for name in (
        "erro_dht",
        "alerta_temperatura",
        "alerta_umidade",
        "alerta_qualidade_ar",
        "alerta_geral",
        "led_verde",
        "led_vermelho",
        "buzzer",
        "buzzer_alerta",
        "ventilacao_ligada",
        "rele_ligado",
        "rele_habilitado",
    ):
        if item[name] is not None:
            item[name] = bool(item[name])
    if item["motivos_alerta"] is not None:
        item["motivos_alerta"] = json.loads(item["motivos_alerta"])
    return item


def mais_recente() -> dict | None:
    with conectar() as banco:
        row = banco.execute("SELECT * FROM leituras ORDER BY id DESC LIMIT 1").fetchone()
    return _formatar(row)


def historico(horas: int, limite: int) -> list[dict]:
    with conectar() as banco:
        rows = banco.execute(
            """SELECT * FROM leituras
               WHERE datetime(criado_em) >= datetime('now', ?)
               ORDER BY id DESC LIMIT ?""",
            (f"-{horas} hours", limite),
        ).fetchall()
    return [_formatar(row) for row in rows]
