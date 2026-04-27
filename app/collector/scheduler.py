# app/collector/scheduler.py
"""
Production scheduler.
- Discovery:  every 15 minutes per account (finds new/removed resources)
- Metrics:    every 60 seconds per account (collects CloudWatch data)
- Alerts:     every 60 seconds after metrics (evaluates thresholds)
- Partitions: monthly (adds next month's DB partition)

Run standalone: venv\Scripts\python -m app.collector.scheduler
Or called from main.py startup as background task.
"""
import time
import logging
import threading
from datetime import datetime
from app.db import get_connection
import signal
_stop_event = threading.Event()

logger = logging.getLogger(__name__)

# ── Intervals ─────────────────────────────────────────────────
METRICS_INTERVAL_SECONDS   = 60    # collect metrics every 60s
DISCOVERY_INTERVAL_SECONDS = 900   # discover resources every 15min
PARTITION_INTERVAL_SECONDS = 86400 # check partitions daily


def _get_active_accounts():
    conn   = get_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT id, account_name, account_id,
               role_arn, external_id, default_region
        FROM aws_accounts
        WHERE status = 'active'
    """)
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return rows


def _ensure_next_partition():
    """
    Adds partition for next month if it doesn't exist yet.
    Runs daily.
    """
    try:
        from datetime import date
        import calendar

        conn   = get_connection()
        cursor = conn.cursor()

        # Calculate next month boundary
        today      = date.today()
        if today.month == 12:
            next_year  = today.year + 1
            next_month = 1
        else:
            next_year  = today.year
            next_month = today.month + 1

        # Month after next (partition upper bound)
        if next_month == 12:
            bound_year  = next_year + 1
            bound_month = 1
        else:
            bound_year  = next_year
            bound_month = next_month + 1

        partition_name = f"p{next_year}_{next_month:02d}"
        bound_date     = f"{bound_year}-{bound_month:02d}-01"

        # Check if partition already exists
        cursor.execute("""
            SELECT PARTITION_NAME
            FROM information_schema.PARTITIONS
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME   = 'metrics'
              AND PARTITION_NAME = %s
        """, (partition_name,))

        if cursor.fetchone():
            cursor.close()
            conn.close()
            return  # Already exists

        # Add partition by reorganizing p_future
        sql = f"""
            ALTER TABLE metrics REORGANIZE PARTITION p_future INTO (
                PARTITION {partition_name} VALUES LESS THAN (TO_DAYS('{bound_date}')),
                PARTITION p_future VALUES LESS THAN MAXVALUE
            )
        """
        cursor.execute(sql)
        conn.commit()
        logger.info(f"Added partition: {partition_name} (bound: {bound_date})")

        cursor.close()
        conn.close()

    except Exception as e:
        logger.error(f"Partition management error: {e}")


def run_once():
    """
    Single full collection cycle:
    1. Discovery (if due)
    2. Metrics collection
    3. Alert evaluation
    """
    from app.collector.discovery.runner import run_discovery
    from app.collector.metrics.runner   import run_metrics_collection
    from app.collector.alert_evaluator  import evaluate_alerts

    accounts = _get_active_accounts()
    if not accounts:
        logger.warning("No active accounts found")
        return

    logger.info(f"Collection cycle started — {len(accounts)} accounts")

    # Step 1: Collect metrics for all accounts in parallel
    run_metrics_collection(accounts)

    # Step 2: Evaluate alerts immediately after metrics
    evaluate_alerts()

    logger.info("Collection cycle complete")


def run_discovery_once():
    from app.collector.discovery.runner import run_discovery
    run_discovery()


def run_loop():
    last_discovery  = 0
    last_partition  = 0
    cycle           = 0

    logger.info("Scheduler loop started")

    while not _stop_event.is_set():
        now = time.time()
        cycle += 1

        # Discovery every 15 minutes
        if now - last_discovery >= DISCOVERY_INTERVAL_SECONDS:
            logger.info(f"[Cycle {cycle}] Running discovery...")
            try:
                run_discovery_once()
                last_discovery = now
            except Exception as e:
                logger.error(f"Discovery error: {e}")

        # Partition check daily
        if now - last_partition >= PARTITION_INTERVAL_SECONDS:
            try:
                _ensure_next_partition()
                last_partition = now
            except Exception as e:
                logger.error(f"Partition check error: {e}")

        # Metrics + alerts every cycle
        logger.info(f"[Cycle {cycle}] Collecting metrics...")
        try:
            run_once()
        except Exception as e:
            logger.error(f"Collection cycle error: {e}")

        # Sleep until next cycle
        elapsed = time.time() - now
        sleep   = max(0, METRICS_INTERVAL_SECONDS - elapsed)
        logger.info(f"[Cycle {cycle}] Done in {elapsed:.1f}s. Next in {sleep:.0f}s.")
        _stop_event.wait(timeout=sleep)


# ── Standalone entry point ────────────────────────────────────

def run():
    """Called manually or for single-shot testing."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    logger.info("Running single collection cycle...")
    run_discovery_once()
    run_once()
    logger.info("Done.")


if __name__ == "__main__":
    run()