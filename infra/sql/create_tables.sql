-- Run once after Redshift Serverless workgroup is ready.
-- deploy.sh calls this via: aws redshift-data execute-statement

CREATE SCHEMA IF NOT EXISTS mag10;

CREATE TABLE IF NOT EXISTS mag10.volume_spikes (
    symbol        VARCHAR(10)    NOT NULL,
    signal_type   VARCHAR(20)    NOT NULL DEFAULT 'volume_spike',
    timestamp_ms  BIGINT         NOT NULL,
    price         DECIMAL(12,4),
    volume        DECIMAL(18,4),
    avg_volume    DECIMAL(18,4),
    spike_ratio   DECIMAL(8,4),
    ml_score      DECIMAL(5,4),
    PRIMARY KEY (symbol, timestamp_ms)
);

CREATE TABLE IF NOT EXISTS mag10.momentum_signals (
    symbol          VARCHAR(10)  NOT NULL,
    signal_type     VARCHAR(20)  NOT NULL DEFAULT 'momentum',
    timestamp_ms    BIGINT       NOT NULL,
    open_price      DECIMAL(12,4),
    close_price     DECIMAL(12,4),
    pct_change      DECIMAL(8,4),
    direction       VARCHAR(4),
    candle_start_ms BIGINT,
    candle_end_ms   BIGINT,
    ml_score        DECIMAL(5,4),
    PRIMARY KEY (symbol, timestamp_ms)
);

CREATE TABLE IF NOT EXISTS mag10.volatility_spikes (
    symbol       VARCHAR(10)  NOT NULL,
    signal_type  VARCHAR(20)  NOT NULL DEFAULT 'volatility_spike',
    timestamp_ms BIGINT       NOT NULL,
    price        DECIMAL(12,4),
    z_score      DECIMAL(8,4),
    std_dev      DECIMAL(12,4),
    window_secs  INTEGER,
    ml_score     DECIMAL(5,4),
    PRIMARY KEY (symbol, timestamp_ms)
);

CREATE TABLE IF NOT EXISTS mag10.sector_snapshots (
    symbol       VARCHAR(10)  NOT NULL,
    signal_type  VARCHAR(20)  NOT NULL DEFAULT 'sector_snapshot',
    timestamp_ms BIGINT       NOT NULL,
    open_price   DECIMAL(12,4),
    last_price   DECIMAL(12,4),
    pct_change   DECIMAL(8,4),
    trade_count  INTEGER,
    is_stale     BOOLEAN,
    PRIMARY KEY (symbol, timestamp_ms)
);
