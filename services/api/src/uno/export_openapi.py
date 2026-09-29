"""Exporta el contrato OpenAPI. Uso: ``python -m uno.export_openapi > openapi.json``.

El frontend genera sus tipos desde este archivo: un cambio de contrato rompe el build, no el campo
(doc 01 §7, ``openapi-typescript``).
"""

from __future__ import annotations

import json
import sys

from uno.config import Settings
from uno.main import create_app


def main() -> None:
    app = create_app(
        Settings(env="test", database_url="sqlite+aiosqlite:///:memory:", push_backend="memory")
    )
    sys.stdout.write(json.dumps(app.openapi(), indent=2, ensure_ascii=False, sort_keys=True))
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
