"""Export and import SQLite backups without overwriting existing readings."""

import argparse
import shutil
import sqlite3
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import BinaryIO

from smartair import database


def export_database(output: BinaryIO) -> None:
    source_path = database.DATABASE_PATH.resolve()
    if not source_path.is_file():
        raise FileNotFoundError("Banco não encontrado. Inicie a API antes de exportar.")
    with TemporaryDirectory(prefix="smartair-backup-") as folder:
        snapshot = Path(folder) / "snapshot.db"
        source = sqlite3.connect(source_path.as_uri() + "?mode=ro", uri=True)
        destination = sqlite3.connect(snapshot)
        try:
            source.backup(destination)
        finally:
            destination.close()
            source.close()
        with snapshot.open("rb") as stream:
            shutil.copyfileobj(stream, output)


def import_database(source: BinaryIO) -> None:
    target = database.DATABASE_PATH
    if target.exists():
        raise FileExistsError("Já existe um banco no destino; a importação não sobrescreve dados.")
    with TemporaryDirectory(prefix="smartair-import-") as folder:
        snapshot = Path(folder) / "snapshot.db"
        with snapshot.open("wb") as stream:
            shutil.copyfileobj(source, stream)
        with snapshot.open("rb") as stream:
            if stream.read(16) != b"SQLite format 3\x00":
                raise ValueError("O arquivo recebido não é um banco SQLite válido.")
        connection = sqlite3.connect(snapshot.as_uri() + "?mode=ro", uri=True)
        try:
            if connection.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                raise ValueError("O backup falhou na verificação de integridade.")
            fields = {row[1] for row in connection.execute("PRAGMA table_info(leituras)")}
            if not {"id", "temperatura", "umidade", "criado_em"}.issubset(fields):
                raise ValueError("O arquivo não contém a tabela de leituras do SmartAir.")
        finally:
            connection.close()
        target.parent.mkdir(parents=True, exist_ok=True)
        with snapshot.open("rb") as original, target.open("xb") as destination:
            try:
                shutil.copyfileobj(original, destination)
            except Exception:
                target.unlink(missing_ok=True)
                raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("export", "import"))
    action = parser.parse_args().action
    try:
        if action == "export":
            export_database(sys.stdout.buffer)
        else:
            import_database(sys.stdin.buffer)
            print("Backup importado. Inicie a API para atualizar o esquema.", file=sys.stderr)
    except (OSError, sqlite3.Error, ValueError) as error:
        parser.exit(1, f"Erro: {error}\n")


if __name__ == "__main__":
    main()
