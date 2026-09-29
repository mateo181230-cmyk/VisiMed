"""Identificadores. UUIDv7 (ordenable por tiempo), generable sin red (doc 01 §3, principio 5)."""

from __future__ import annotations

import os
import time
import uuid


def uuid7() -> uuid.UUID:
    """UUID versión 7 (RFC 9562): 48 bits de milisegundos Unix + 74 bits aleatorios."""
    ts_ms = time.time_ns() // 1_000_000
    rand = os.urandom(10)
    b = bytearray(16)
    b[0:6] = ts_ms.to_bytes(6, "big")
    b[6] = 0x70 | (rand[0] & 0x0F)
    b[7] = rand[1]
    b[8] = 0x80 | (rand[2] & 0x3F)
    b[9:16] = rand[3:10]
    return uuid.UUID(bytes=bytes(b))
