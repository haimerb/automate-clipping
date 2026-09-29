"""Limpieza de disco del storage de edgetape.

    python -m app.cleanup                  # sweep conservador (7 días, 1 versión)
    python -m app.cleanup --days 30 --keep 2
    python -m app.cleanup --job <id> --purge

Qué hace:
- `previous/`: conserva solo las N versiones más recientes de cada job y borra
  las más antiguas que superen `--days`.
- `ai_tmp/`: borra carpetas de scene files de jobs ya terminados hace más de
  `--days` o de jobs que ya no existen (fallo a mitad del render).
- `--purge`: vacía por completo la media (fuente + exports) de un job, igual que
  `DELETE /api/jobs/{id}/media` pero sin necesitar el servidor ni el token.
"""

from __future__ import annotations

import argparse
import os

from .storage import JobStore


def main() -> int:
    parser = argparse.ArgumentParser(description="Limpieza de storage de edgetape")
    parser.add_argument(
        "--storage",
        default=os.environ.get("EDGETAPE_STORAGE", "backend/storage"),
        help="raíz del storage (por defecto $EDGETAPE_STORAGE)",
    )
    parser.add_argument("--days", type=float, default=7.0, help="edad mínima para borrar")
    parser.add_argument("--keep", type=int, default=1, help="versiones a conservar en previous/")
    parser.add_argument("--job", help="purga la media de un job concreto y sale")
    args = parser.parse_args()

    store = JobStore(args.storage)

    if args.job:
        job = store.get_job(args.job)
        if job is None:
            print(f"no existe el job {args.job} en {store.root}")
            return 1
        freed = store.purge_media(args.job)
        print(f"job {args.job}: liberados {freed / (1024 * 1024):.1f} MB")
        return 0

    result = store.sweep_media(max_age_days=args.days, keep=args.keep)
    mb = result["bytes"] / (1024 * 1024)
    print(f"storage {store.root}: {result['files']} archivos, {mb:.1f} MB liberados")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
