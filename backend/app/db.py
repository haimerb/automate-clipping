from __future__ import annotations

import os

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


def database_url() -> str:
    """URL de conexión SOLO desde el entorno (EDGETAPE_DATABASE_URL o DATABASE_URL).
    Nunca se queman credenciales en el código."""
    url = os.environ.get("EDGETAPE_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError(
            "Falta EDGETAPE_DATABASE_URL (o DATABASE_URL). "
            "Defínela en un archivo .env (ver .env.example) o en el entorno."
        )
    return url


def _connect_args(url: str) -> dict:
    if url.startswith("sqlite"):
        return {"check_same_thread": False}
    return {}


engine = create_engine(
    database_url(),
    pool_pre_ping=True,
    connect_args=_connect_args(database_url()),
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


# Columnas añadidas con el tiempo: create_all es idempotente y no altera tablas
# existentes, así que se agregan con ALTER TABLE cuando faltan.
_MIGRATIONS = [
    ("linked_accounts", "client_id", "VARCHAR(255)"),
    ("linked_accounts", "client_secret", "VARCHAR(255)"),
    ("linked_accounts", "redirect_uri", "VARCHAR(512)"),
]


def _migrate(engine) -> None:
    insp = inspect(engine)
    for table, column, coltype in _MIGRATIONS:
        if table not in insp.get_table_names():
            continue
        if column in {c["name"] for c in insp.get_columns(table)}:
            continue
        with engine.begin() as conn:
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {coltype}"))


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
    _migrate(engine)


def get_db():
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()
