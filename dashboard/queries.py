import os

import pandas as pd
import psycopg2


def _conn():
    return psycopg2.connect(
        host=os.environ["REDSHIFT_HOST"],
        port=5439,
        dbname=os.environ["REDSHIFT_DB"],
        user=os.environ["REDSHIFT_USER"],
        password=os.environ["REDSHIFT_PASSWORD"],
        sslmode="require",
    )


def _q(sql: str, params: tuple = ()) -> pd.DataFrame:
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
            cols = [d[0] for d in cur.description]
        return pd.DataFrame(rows, columns=cols)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Tab 1: Live Signals
# ---------------------------------------------------------------------------

def get_market_breadth() -> pd.DataFrame:
    return _q("""
        SELECT symbol, pct_change, last_price, is_stale
        FROM signals.sector_snapshots
        WHERE snapshot_ts = (SELECT MAX(snapshot_ts) FROM signals.sector_snapshots)
        ORDER BY symbol
    """)


def get_signal_clusters(minutes_back: int = 60) -> pd.DataFrame:
    return _q("""
        WITH all_signals AS (
            SELECT symbol, detected_at FROM signals.volume_spikes
            WHERE date_trunc('day', detected_at) = CURRENT_DATE
            UNION ALL
            SELECT symbol, detected_at FROM signals.momentum_signals
            WHERE date_trunc('day', detected_at) = CURRENT_DATE
            UNION ALL
            SELECT symbol, detected_at FROM signals.volatility_spikes
            WHERE date_trunc('day', detected_at) = CURRENT_DATE
        ),
        bucketed AS (
            SELECT
                DATEADD(minute,
                    -(EXTRACT(MINUTE FROM detected_at)::INT %% 2),
                    date_trunc('minute', detected_at)
                ) AS bucket,
                symbol
            FROM all_signals
            WHERE detected_at >= DATEADD(minute, -%s, GETDATE())
        )
        SELECT bucket, COUNT(DISTINCT symbol) AS symbol_count, COUNT(*) AS signal_count
        FROM bucketed
        GROUP BY bucket
        HAVING COUNT(DISTINCT symbol) >= 3
        ORDER BY bucket DESC
    """, (minutes_back,))


def get_session_leaderboard() -> pd.DataFrame:
    return _q("""
        SELECT symbol, COUNT(*) AS signal_count
        FROM (
            SELECT symbol FROM signals.volume_spikes
            WHERE date_trunc('day', detected_at) = CURRENT_DATE
            UNION ALL
            SELECT symbol FROM signals.momentum_signals
            WHERE date_trunc('day', detected_at) = CURRENT_DATE
            UNION ALL
            SELECT symbol FROM signals.volatility_spikes
            WHERE date_trunc('day', detected_at) = CURRENT_DATE
        )
        GROUP BY symbol
        ORDER BY signal_count DESC
        LIMIT 5
    """)


def get_opening_range(date_str: str) -> pd.DataFrame:
    return _q("""
        WITH orb AS (
            SELECT symbol,
                MIN(last_price) AS orb_low,
                MAX(last_price) AS orb_high
            FROM signals.sector_snapshots
            WHERE date_trunc('day', snapshot_ts) = %s::DATE
              AND snapshot_ts <= DATEADD(minute, 30,
                    TIMESTAMP %s || ' 09:30:00')
            GROUP BY symbol
        )
        SELECT vs.symbol, vs.detected_at, vs.price, vs.spike_ratio,
               orb.orb_high, orb.orb_low,
               CASE
                   WHEN vs.price > orb.orb_high THEN 'BREAKOUT_UP'
                   WHEN vs.price < orb.orb_low  THEN 'BREAKOUT_DOWN'
                   ELSE 'IN_RANGE'
               END AS orb_status
        FROM signals.volume_spikes vs
        JOIN orb ON orb.symbol = vs.symbol
        WHERE date_trunc('day', vs.detected_at) = %s::DATE
          AND vs.detected_at > DATEADD(minute, 30,
                TIMESTAMP %s || ' 09:30:00')
        ORDER BY vs.detected_at DESC
    """, (date_str, date_str, date_str, date_str))


def get_all_realtime_signals(minutes_back: int = 10) -> pd.DataFrame:
    return _q("""
        SELECT symbol, detected_at, 'volume_spike' AS signal_type,
               spike_ratio AS strength, price, ml_anomaly_score
        FROM signals.volume_spikes
        WHERE detected_at >= DATEADD(minute, -%s, GETDATE())
          AND date_trunc('day', detected_at) = CURRENT_DATE
        UNION ALL
        SELECT symbol, detected_at, 'momentum_signal',
               ABS(pct_change), latest_close, ml_anomaly_score
        FROM signals.momentum_signals
        WHERE detected_at >= DATEADD(minute, -%s, GETDATE())
          AND date_trunc('day', detected_at) = CURRENT_DATE
        UNION ALL
        SELECT symbol, detected_at, 'volatility_spike',
               z_score, price, ml_anomaly_score
        FROM signals.volatility_spikes
        WHERE detected_at >= DATEADD(minute, -%s, GETDATE())
          AND date_trunc('day', detected_at) = CURRENT_DATE
        ORDER BY detected_at DESC
    """, (minutes_back, minutes_back, minutes_back))


# ---------------------------------------------------------------------------
# Tab 2: Volume Analysis
# ---------------------------------------------------------------------------

def get_rvol(date_str: str) -> pd.DataFrame:
    return _q("""
        WITH today AS (
            SELECT EXTRACT(HOUR FROM detected_at) AS hour, COUNT(*) AS cnt
            FROM signals.volume_spikes
            WHERE date_trunc('day', detected_at) = %s::DATE
            GROUP BY 1
        ),
        historical AS (
            SELECT EXTRACT(HOUR FROM detected_at) AS hour,
                   COUNT(*) * 1.0 / COUNT(DISTINCT date_trunc('day', detected_at)) AS avg_cnt
            FROM signals.volume_spikes
            WHERE detected_at >= DATEADD(day, -30, %s::DATE)
              AND detected_at < %s::DATE
            GROUP BY 1
        )
        SELECT t.hour, t.cnt AS today_count,
               COALESCE(h.avg_cnt, 0) AS hist_avg,
               CASE WHEN COALESCE(h.avg_cnt, 0) > 0
                    THEN t.cnt / h.avg_cnt ELSE NULL END AS rvol
        FROM today t
        LEFT JOIN historical h ON h.hour = t.hour
        ORDER BY t.hour
    """, (date_str, date_str, date_str))


def get_best_hours(date_str: str) -> pd.DataFrame:
    return _q("""
        SELECT EXTRACT(HOUR FROM detected_at) AS hour,
               COUNT(*) AS signal_count,
               AVG(spike_ratio) AS avg_ratio,
               MAX(spike_ratio) AS max_ratio
        FROM signals.volume_spikes
        WHERE date_trunc('day', detected_at) = %s::DATE
        GROUP BY 1
        ORDER BY 1
    """, (date_str,))


def get_signal_strength(date_range_days: int = 30) -> pd.DataFrame:
    return _q("""
        SELECT
            CASE
                WHEN spike_ratio < 5  THEN 'Mild (4-5x)'
                WHEN spike_ratio < 8  THEN 'Moderate (5-8x)'
                WHEN spike_ratio < 12 THEN 'Strong (8-12x)'
                ELSE 'Extreme (12x+)'
            END AS bucket,
            COUNT(*) AS signal_count,
            AVG(ABS(ss.pct_change)) AS avg_abs_move
        FROM signals.volume_spikes vs
        LEFT JOIN signals.sector_snapshots ss
            ON ss.symbol = vs.symbol
            AND ss.snapshot_ts BETWEEN DATEADD(minute, 15, vs.detected_at)
                                   AND DATEADD(minute, 30, vs.detected_at)
        WHERE vs.detected_at >= DATEADD(day, -%s, CURRENT_DATE)
        GROUP BY 1
        ORDER BY MIN(spike_ratio)
    """, (date_range_days,))


# ---------------------------------------------------------------------------
# Tab 3: Momentum & Correlation
# ---------------------------------------------------------------------------

def get_multi_signal_confirmation(date_str: str) -> pd.DataFrame:
    return _q("""
        SELECT vs.symbol, vs.detected_at AS vol_time,
               ms.detected_at AS mom_time,
               DATEDIFF(second, vs.detected_at, ms.detected_at) AS seconds_apart,
               vs.spike_ratio, ms.direction
        FROM signals.volume_spikes vs
        JOIN signals.momentum_signals ms
            ON ms.symbol = vs.symbol
            AND ABS(DATEDIFF(second, vs.detected_at, ms.detected_at)) <= 300
        WHERE date_trunc('day', vs.detected_at) = %s::DATE
        ORDER BY vs.detected_at DESC
    """, (date_str,))


def get_stock_correlation(date_range_days: int = 30) -> pd.DataFrame:
    return _q("""
        SELECT a.symbol AS symbol_a, b.symbol AS symbol_b,
               COUNT(*) AS co_signal_count
        FROM signals.volume_spikes a
        JOIN signals.volume_spikes b
            ON b.symbol > a.symbol
            AND ABS(DATEDIFF(second, a.detected_at, b.detected_at)) <= 600
            AND date_trunc('day', a.detected_at) = date_trunc('day', b.detected_at)
        WHERE a.detected_at >= DATEADD(day, -%s, CURRENT_DATE)
        GROUP BY 1, 2
        ORDER BY co_signal_count DESC
        LIMIT 20
    """, (date_range_days,))


# ---------------------------------------------------------------------------
# Tab 4: Volatility & Sector
# ---------------------------------------------------------------------------

def get_volatility_regime(date_range_days: int = 7) -> pd.DataFrame:
    return _q("""
        SELECT date_trunc('day', detected_at) AS day,
               COUNT(*) AS signal_count,
               AVG(z_score) AS avg_z,
               MAX(z_score) AS max_z
        FROM signals.volatility_spikes
        WHERE detected_at >= DATEADD(day, -%s, CURRENT_DATE)
        GROUP BY 1
        ORDER BY 1
    """, (date_range_days,))


def get_sector_rotation(date_str: str) -> pd.DataFrame:
    return _q("""
        SELECT EXTRACT(HOUR FROM detected_at) AS hour,
               'volume' AS signal_type, COUNT(*) AS cnt
        FROM signals.volume_spikes
        WHERE date_trunc('day', detected_at) = %s::DATE
        GROUP BY 1, 2
        UNION ALL
        SELECT EXTRACT(HOUR FROM detected_at), 'momentum', COUNT(*)
        FROM signals.momentum_signals
        WHERE date_trunc('day', detected_at) = %s::DATE
        GROUP BY 1, 2
        UNION ALL
        SELECT EXTRACT(HOUR FROM detected_at), 'volatility', COUNT(*)
        FROM signals.volatility_spikes
        WHERE date_trunc('day', detected_at) = %s::DATE
        GROUP BY 1, 2
        ORDER BY 1, 2
    """, (date_str, date_str, date_str))


# ---------------------------------------------------------------------------
# Tab 5: Analytics
# ---------------------------------------------------------------------------

def get_signal_accuracy(date_range_days: int = 30, min_spike_ratio: float = 4.0) -> pd.DataFrame:
    return _q("""
        WITH signals_exit AS (
            SELECT vs.symbol, vs.detected_at, vs.price AS entry,
                   vs.spike_ratio,
                   AVG(ss.last_price) AS exit_price
            FROM signals.volume_spikes vs
            LEFT JOIN signals.sector_snapshots ss
                ON ss.symbol = vs.symbol
                AND ss.snapshot_ts BETWEEN DATEADD(minute, 15, vs.detected_at)
                                       AND DATEADD(minute, 30, vs.detected_at)
            WHERE vs.detected_at >= DATEADD(day, -%s, CURRENT_DATE)
              AND vs.spike_ratio >= %s
            GROUP BY vs.symbol, vs.detected_at, vs.price, vs.spike_ratio
        )
        SELECT
            COUNT(*) AS total_signals,
            SUM(CASE WHEN (exit_price - entry) / entry * 100 >= 1.0 THEN 1 ELSE 0 END) AS wins,
            ROUND(100.0 * SUM(CASE WHEN (exit_price - entry) / entry * 100 >= 1.0 THEN 1 ELSE 0 END)
                  / NULLIF(COUNT(*), 0), 1) AS win_rate_pct,
            ROUND(AVG((exit_price - entry) / entry * 100), 3) AS avg_return_pct,
            SUM(CASE WHEN (exit_price - entry) / entry * 100 >= 2.0 THEN 1 ELSE 0 END) AS wins_2pct
        FROM signals_exit
        WHERE exit_price IS NOT NULL
    """, (date_range_days, min_spike_ratio))


def get_symbol_win_rates(date_range_days: int = 30, min_spike_ratio: float = 4.0) -> pd.DataFrame:
    return _q("""
        WITH signals_exit AS (
            SELECT vs.symbol, vs.price AS entry, AVG(ss.last_price) AS exit_price
            FROM signals.volume_spikes vs
            LEFT JOIN signals.sector_snapshots ss
                ON ss.symbol = vs.symbol
                AND ss.snapshot_ts BETWEEN DATEADD(minute, 15, vs.detected_at)
                                       AND DATEADD(minute, 30, vs.detected_at)
            WHERE vs.detected_at >= DATEADD(day, -%s, CURRENT_DATE)
              AND vs.spike_ratio >= %s
            GROUP BY vs.symbol, vs.price
        )
        SELECT symbol,
               COUNT(*) AS total,
               ROUND(100.0 * SUM(CASE WHEN (exit_price - entry) / entry * 100 >= 1.0
                                      THEN 1 ELSE 0 END) / NULLIF(COUNT(*), 0), 1) AS win_rate_pct,
               ROUND(AVG((exit_price - entry) / entry * 100), 3) AS avg_return_pct
        FROM signals_exit
        WHERE exit_price IS NOT NULL
        GROUP BY symbol
        HAVING COUNT(*) >= 3
        ORDER BY win_rate_pct DESC
    """, (date_range_days, min_spike_ratio))


def get_per_signal_pnl(date_range_days: int = 30) -> pd.DataFrame:
    return _q("""
        SELECT vs.symbol, vs.detected_at, vs.price AS entry_price, vs.spike_ratio,
               s15.last_price AS exit_5min,
               s30.last_price AS exit_15min,
               s60.last_price AS exit_30min,
               vs.ml_anomaly_score
        FROM signals.volume_spikes vs
        LEFT JOIN signals.sector_snapshots s15
            ON s15.symbol = vs.symbol
            AND s15.snapshot_ts = (
                SELECT MIN(snapshot_ts) FROM signals.sector_snapshots
                WHERE symbol = vs.symbol
                  AND snapshot_ts BETWEEN DATEADD(minute, 4, vs.detected_at)
                                      AND DATEADD(minute, 6, vs.detected_at)
            )
        LEFT JOIN signals.sector_snapshots s30
            ON s30.symbol = vs.symbol
            AND s30.snapshot_ts = (
                SELECT MIN(snapshot_ts) FROM signals.sector_snapshots
                WHERE symbol = vs.symbol
                  AND snapshot_ts BETWEEN DATEADD(minute, 14, vs.detected_at)
                                      AND DATEADD(minute, 16, vs.detected_at)
            )
        LEFT JOIN signals.sector_snapshots s60
            ON s60.symbol = vs.symbol
            AND s60.snapshot_ts = (
                SELECT MIN(snapshot_ts) FROM signals.sector_snapshots
                WHERE symbol = vs.symbol
                  AND snapshot_ts BETWEEN DATEADD(minute, 29, vs.detected_at)
                                      AND DATEADD(minute, 31, vs.detected_at)
            )
        WHERE vs.detected_at >= DATEADD(day, -%s, CURRENT_DATE)
        ORDER BY vs.detected_at DESC
        LIMIT 200
    """, (date_range_days,))


# ---------------------------------------------------------------------------
# Tab 6: ML Insights
# ---------------------------------------------------------------------------

def get_ml_score_distribution(date_str: str) -> pd.DataFrame:
    return _q("""
        SELECT ml_anomaly_score, 'volume_spike' AS signal_type
        FROM signals.volume_spikes
        WHERE date_trunc('day', detected_at) = %s::DATE
          AND ml_anomaly_score IS NOT NULL
        UNION ALL
        SELECT ml_anomaly_score, 'momentum_signal'
        FROM signals.momentum_signals
        WHERE date_trunc('day', detected_at) = %s::DATE
          AND ml_anomaly_score IS NOT NULL
        UNION ALL
        SELECT ml_anomaly_score, 'volatility_spike'
        FROM signals.volatility_spikes
        WHERE date_trunc('day', detected_at) = %s::DATE
          AND ml_anomaly_score IS NOT NULL
    """, (date_str, date_str, date_str))


def get_ml_score_vs_strength(date_str: str) -> pd.DataFrame:
    return _q("""
        SELECT symbol, spike_ratio AS strength, ml_anomaly_score, 'volume_spike' AS signal_type
        FROM signals.volume_spikes
        WHERE date_trunc('day', detected_at) = %s::DATE
          AND ml_anomaly_score IS NOT NULL
        UNION ALL
        SELECT symbol, z_score, ml_anomaly_score, 'volatility_spike'
        FROM signals.volatility_spikes
        WHERE date_trunc('day', detected_at) = %s::DATE
          AND ml_anomaly_score IS NOT NULL
    """, (date_str, date_str))


def get_ml_confirmed_signals(date_str: str, min_score: float = 0.75) -> pd.DataFrame:
    return _q("""
        SELECT symbol, detected_at, spike_ratio AS strength,
               ml_anomaly_score, price, 'volume_spike' AS signal_type
        FROM signals.volume_spikes
        WHERE date_trunc('day', detected_at) = %s::DATE
          AND ml_anomaly_score >= %s
        UNION ALL
        SELECT symbol, detected_at, z_score,
               ml_anomaly_score, price, 'volatility_spike'
        FROM signals.volatility_spikes
        WHERE date_trunc('day', detected_at) = %s::DATE
          AND ml_anomaly_score >= %s
        UNION ALL
        SELECT symbol, detected_at, ABS(pct_change),
               ml_anomaly_score, latest_close, 'momentum_signal'
        FROM signals.momentum_signals
        WHERE date_trunc('day', detected_at) = %s::DATE
          AND ml_anomaly_score >= %s
        ORDER BY ml_anomaly_score DESC
    """, (date_str, min_score, date_str, min_score, date_str, min_score))
