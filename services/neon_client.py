"""
Neon DB client — read-only access to NEPSE OHLCV data.

Uses psycopg2 directly (NOT Django ORM) to prevent accidental migrations.
All queries are SELECT-only. Never INSERT, UPDATE, or DELETE.

This is the ONLY file that touches the Neon DB.
All other services call functions from here.
"""

import psycopg2
import psycopg2.extras
import threading
import time
import logging
from django.conf import settings

logger = logging.getLogger('nepse_rag')

_keepalive_started = False
_keepalive_lock = threading.Lock()


# ── Connection ─────────────────────────────────────────────────

def get_neon_connection():
    """
    Returns a new psycopg2 connection to Neon DB.
    Uses connection string from settings.NEON_DATABASE_URL.
    Always uses sslmode=require (Neon requires SSL).
    Caller is responsible for closing the connection.
    """
    try:
        conn = psycopg2.connect(settings.NEON_DATABASE_URL)
        return conn
    except psycopg2.Error as e:
        logger.error(f"Failed to connect to Neon DB: {e}",
                     extra={'event': 'neon_connect_error'})
        raise RuntimeError(f"Neon DB connection failed: {e}") from e


def execute_neon_query(sql: str, params: tuple = None) -> list[dict]:
    """
    Executes a SELECT query against Neon DB.
    Opens connection, executes, closes connection, returns results.
    Returns list of dicts (column_name → value).
    Raises RuntimeError with helpful message on connection failure.
    Never allows non-SELECT statements (raises ValueError if detected).

    Usage:
        rows = execute_neon_query(
            "SELECT * FROM stocks_stockdata WHERE symbol = %s "
            "ORDER BY date DESC LIMIT 100",
            ('NABIL',)
        )
    """
    # Guard: only allow SELECT statements
    cleaned = sql.strip().upper()
    if not cleaned.startswith('SELECT'):
        raise ValueError(
            "Only SELECT queries are allowed against Neon DB. "
            f"Received: {sql[:50]}..."
        )

    conn = None
    try:
        conn = get_neon_connection()
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
            # Convert RealDictRow objects to regular dicts
            return [dict(row) for row in rows]
    except psycopg2.Error as e:
        logger.error(f"Neon DB query failed: {e}",
                     extra={'event': 'neon_query_error', 'sql': sql[:100]})
        raise RuntimeError(f"Neon DB query failed: {e}") from e
    finally:
        if conn:
            conn.close()


# ── Keep-Alive ─────────────────────────────────────────────────

def _keepalive_worker():
    """
    Background thread that pings Neon DB every N seconds.
    Prevents serverless cold starts during demos.
    Logs ping result (success or failure) at DEBUG level.
    Runs as daemon thread — stops automatically when Django stops.
    """
    interval = getattr(settings, 'NEON_KEEPALIVE_INTERVAL', 240)
    while True:
        try:
            execute_neon_query("SELECT 1")
            logger.debug("Neon DB keep-alive ping: OK")
        except Exception as e:
            logger.warning(f"Neon DB keep-alive ping failed: {e}",
                           extra={'event': 'neon_keepalive_fail'})
        time.sleep(interval)


def start_keepalive():
    """
    Starts the keep-alive background thread.
    Call this from AppConfig.ready() — once only.
    Safe to call multiple times (checks if already running).
    """
    global _keepalive_started
    with _keepalive_lock:
        if _keepalive_started:
            return
        _keepalive_started = True

    thread = threading.Thread(
        target=_keepalive_worker,
        daemon=True,
        name='neon-keepalive'
    )
    thread.start()
    interval = getattr(settings, 'NEON_KEEPALIVE_INTERVAL', 240)
    logger.info(
        f"Neon DB keep-alive started (interval: {interval}s)",
        extra={'event': 'neon_keepalive_start', 'interval': interval}
    )


# ── Health Check ───────────────────────────────────────────────

def test_neon_connection() -> dict:
    """
    Tests the Neon DB connection and returns status dict.
    Used by /api/health/ endpoint.
    Returns: {connected: bool, latency_ms: int, error: str|None}
    """
    start = time.time()
    try:
        execute_neon_query("SELECT 1")
        latency_ms = int((time.time() - start) * 1000)
        return {
            'connected': True,
            'latency_ms': latency_ms,
            'error': None,
        }
    except Exception as e:
        latency_ms = int((time.time() - start) * 1000)
        return {
            'connected': False,
            'latency_ms': latency_ms,
            'error': str(e),
        }
