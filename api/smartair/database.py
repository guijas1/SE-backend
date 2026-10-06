"""SQLite connection and backward-compatible schema initialization."""

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
    "erro_dht": "INTEGER",
    "alerta_temperatura": "INTEGER",
    "alerta_umidade": "INTEGER",
    "alerta_qualidade_ar": "INTEGER",
    "alerta_geral": "INTEGER",
    "led_verde": "INTEGER",
    "led_vermelho": "INTEGER",
    "buzzer": "INTEGER",
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


def salvar(payload: dict, criado_em: str) -> int:
    values = {**payload, "criado_em": criado_em}
    columns = list(_COLUMNS)
    placeholders = ", ".join("?" for _ in columns)
    query = f"INSERT INTO leituras ({', '.join(columns)}) VALUES ({placeholders})"
    with conectar() as banco:
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
    ):
        if item[name] is not None:
            item[name] = bool(item[name])
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
