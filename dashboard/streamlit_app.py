import os
from datetime import date, datetime, timezone

import boto3
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from streamlit_autorefresh import st_autorefresh

import queries

# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

def _check_password() -> bool:
    def _submit():
        if st.session_state["pw"] == os.environ["DASHBOARD_PASSWORD"]:
            st.session_state["auth"] = True
        else:
            st.session_state["auth_failed"] = True

    if st.session_state.get("auth"):
        return True
    st.title("mag10 Monitor")
    st.text_input("Password", type="password", key="pw", on_change=_submit)
    if st.session_state.get("auth_failed"):
        st.error("Wrong password")
    return False


if not _check_password():
    st.stop()

# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

st.set_page_config(page_title="mag10 Monitor", layout="wide")

with st.sidebar:
    st.title("mag10 Monitor")
    selected_date = st.date_input("Date", value=date.today())
    date_str = selected_date.strftime("%Y-%m-%d")

    all_symbols = ["AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA", "AMD", "AVGO", "PLTR"]
    selected_symbols = st.multiselect("Symbols", all_symbols, default=all_symbols)

    refresh_secs = st.selectbox("Auto-refresh", [15, 30, 60, 120], index=1)

st_autorefresh(interval=refresh_secs * 1000, key="autorefresh")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _signal_score(signal_type: str, row) -> int:
    if signal_type == "volume_spike":
        return min(10, max(1, int(row["strength"] / 0.5)))
    if signal_type == "volatility_spike":
        return min(10, max(1, int(row["strength"] / 0.3)))
    if signal_type == "momentum_signal":
        return min(10, max(1, int(abs(row["strength"]) / 0.15)))
    return 5


def _filter(df, col="symbol"):
    if df.empty or not selected_symbols:
        return df
    return df[df[col].isin(selected_symbols)]


# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------

tabs = st.tabs([
    "Live Signals", "Volume Analysis", "Momentum & Correlation",
    "Volatility & Sector", "Analytics", "ML Insights",
])

# ---- Tab 1: Live Signals ---------------------------------------------------
with tabs[0]:
    st.header("Live Signals")

    # Market breadth
    breadth = _filter(queries.get_market_breadth())
    if not breadth.empty:
        up = (breadth["pct_change"] > 0).sum()
        down = (breadth["pct_change"] < 0).sum()
        flat = len(breadth) - up - down
        verdict = "BULLISH 🟢" if up > down + 2 else ("BEARISH 🔴" if down > up + 2 else "MIXED 🟡")
        st.metric("Market Breadth", verdict, f"▲{up}  ▼{down}  ─{flat}")

    col1, col2 = st.columns(2)

    # Signal clusters
    with col1:
        st.subheader("Signal Clusters (last 60 min)")
        clusters = queries.get_signal_clusters(60)
        if not clusters.empty:
            recent = clusters[clusters["symbol_count"] >= 3]
            if not recent.empty:
                st.warning(f"⚡ {len(recent)} cluster(s) detected")
            with st.expander("Cluster history"):
                st.dataframe(clusters, use_container_width=True)
        else:
            st.info("No clusters in the last 60 minutes")

    # Session leaderboard
    with col2:
        st.subheader("Session Leaderboard")
        lb = queries.get_session_leaderboard()
        if not lb.empty:
            for _, row in lb.iterrows():
                st.metric(row["symbol"], f"{row['signal_count']} signals")

    # Active signals
    st.subheader("Active Signals (last 10 min)")
    live = _filter(queries.get_all_realtime_signals(10))
    if not live.empty:
        live["score"] = live.apply(
            lambda r: _signal_score(r["signal_type"], r), axis=1
        )
        ml_confirmed = live[live["ml_anomaly_score"].fillna(0) >= 0.75]
        if not ml_confirmed.empty:
            st.success(f"✅ {len(ml_confirmed)} ML-confirmed signal(s) (score ≥ 0.75)")

        top5 = live.nlargest(5, "score")
        for _, row in top5.iterrows():
            st.markdown(
                f"**{row['symbol']}** · {row['signal_type']} · "
                f"strength={row['strength']:.2f} · score={row['score']}/10 · "
                f"ml={row['ml_anomaly_score']:.2f if row['ml_anomaly_score'] else 'N/A'}"
            )

        c1, c2 = st.columns(2)
        with c1:
            fig = px.scatter(
                live, x="detected_at", y="price",
                size="strength", color="signal_type",
                hover_data=["symbol", "score"],
                title="Signal activity (bubble = strength)",
            )
            st.plotly_chart(fig, use_container_width=True)
        with c2:
            fig = px.pie(live, names="signal_type", title="Signal type mix")
            st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No signals in the last 10 minutes")

    # ORB
    st.subheader("Opening Range Breakouts")
    orb = _filter(queries.get_opening_range(date_str))
    if not orb.empty:
        st.dataframe(orb[orb["orb_status"] != "IN_RANGE"], use_container_width=True)
    else:
        st.info("No data")

# ---- Tab 2: Volume Analysis ------------------------------------------------
with tabs[1]:
    st.header("Volume Analysis")

    c1, c2 = st.columns(2)
    with c1:
        st.subheader("Relative Volume (RVOL) by Hour")
        rvol = queries.get_rvol(date_str)
        if not rvol.empty:
            rvol["color"] = rvol["rvol"].apply(
                lambda v: "green" if v and v >= 1.5 else ("orange" if v and v >= 1.0 else "red")
            )
            fig = px.bar(rvol, x="hour", y="rvol", color="color",
                         color_discrete_map="identity", title="RVOL by trading hour")
            fig.add_hline(y=1.0, line_dash="dash", annotation_text="Baseline")
            st.plotly_chart(fig, use_container_width=True)

    with c2:
        st.subheader("Signal Activity by Hour")
        hours = queries.get_best_hours(date_str)
        if not hours.empty:
            fig = go.Figure()
            fig.add_bar(x=hours["hour"], y=hours["signal_count"], name="Signals", yaxis="y1")
            fig.add_scatter(x=hours["hour"], y=hours["avg_ratio"], name="Avg ratio",
                            yaxis="y2", mode="lines+markers")
            fig.update_layout(yaxis2=dict(overlaying="y", side="right"))
            st.plotly_chart(fig, use_container_width=True)

    st.subheader("Signal Strength vs Price Move (30-day)")
    strength = queries.get_signal_strength(30)
    if not strength.empty:
        fig = px.bar(strength, x="bucket", y="avg_abs_move",
                     text="signal_count", title="Avg % move after signal by strength bucket")
        st.plotly_chart(fig, use_container_width=True)

# ---- Tab 3: Momentum & Correlation -----------------------------------------
with tabs[2]:
    st.header("Momentum & Correlation")

    st.subheader("Multi-Signal Confirmation")
    multi = _filter(queries.get_multi_signal_confirmation(date_str))
    if not multi.empty:
        fig = px.scatter(multi, x="seconds_apart", y="spike_ratio",
                         color="direction", hover_data=["symbol"],
                         title="Volume spikes with momentum confirmation (±300s)")
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No confirmed multi-signals today")

    st.subheader("Top Correlated Pairs (30-day)")
    corr = queries.get_stock_correlation(30)
    if not corr.empty:
        fig = px.bar(corr.head(10), x="co_signal_count",
                     y=corr.head(10).apply(lambda r: f"{r['symbol_a']}/{r['symbol_b']}", axis=1),
                     orientation="h", title="Co-signal count (within 600s)")
        st.plotly_chart(fig, use_container_width=True)

# ---- Tab 4: Volatility & Sector --------------------------------------------
with tabs[3]:
    st.header("Volatility & Sector")

    c1, c2 = st.columns(2)
    with c1:
        st.subheader("Volatility Regime (7-day)")
        regime = queries.get_volatility_regime(7)
        if not regime.empty:
            fig = go.Figure()
            fig.add_bar(x=regime["day"], y=regime["signal_count"], name="Signals")
            fig.add_scatter(x=regime["day"], y=regime["avg_z"], name="Avg Z-score",
                            yaxis="y2", mode="lines+markers")
            fig.update_layout(yaxis2=dict(overlaying="y", side="right"))
            st.plotly_chart(fig, use_container_width=True)

    with c2:
        st.subheader("Sector Rotation by Hour")
        rotation = queries.get_sector_rotation(date_str)
        if not rotation.empty:
            fig = px.bar(rotation, x="hour", y="cnt", color="signal_type",
                         barmode="group", title="Signals per hour by type")
            st.plotly_chart(fig, use_container_width=True)

# ---- Tab 5: Analytics -------------------------------------------------------
with tabs[4]:
    st.header("Analytics")

    lookback = st.selectbox("Lookback (days)", [7, 14, 30, 60, 90], index=2, key="lb")
    min_ratio = st.slider("Min spike ratio", 4.0, 10.0, 4.0, 0.5, key="mr")

    accuracy = queries.get_signal_accuracy(lookback, min_ratio)
    if not accuracy.empty:
        row = accuracy.iloc[0]
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Total signals", int(row["total_signals"]))
        c2.metric("Win rate (≥1%)", f"{row['win_rate_pct']}%")
        c3.metric("Avg return", f"{row['avg_return_pct']:.3f}%")
        c4.metric("Wins ≥2%", int(row["wins_2pct"]))

    c1, c2 = st.columns(2)
    with c1:
        st.subheader("Win Rate by Symbol")
        sym_wr = queries.get_symbol_win_rates(lookback, min_ratio)
        if not sym_wr.empty:
            fig = px.bar(sym_wr, x="win_rate_pct", y="symbol",
                         orientation="h", title="Win rate % by symbol")
            st.plotly_chart(fig, use_container_width=True)

    with c2:
        st.subheader("Per-Signal P&L")
        pnl = _filter(queries.get_per_signal_pnl(lookback))
        if not pnl.empty:
            fig = px.scatter(pnl, x="spike_ratio", y="exit_15min",
                             color="symbol", hover_data=["detected_at"],
                             title="Entry spike ratio vs 15-min exit price")
            st.plotly_chart(fig, use_container_width=True)

# ---- Tab 6: ML Insights -----------------------------------------------------
with tabs[5]:
    st.header("ML Insights")

    # Model version chip
    try:
        sm = boto3.client("sagemaker", region_name=os.environ.get("AWS_REGION", "us-east-1"))
        endpoint_name = os.environ.get("SAGEMAKER_ENDPOINT_NAME", "mag10-anomaly-endpoint")
        ep = sm.describe_endpoint(EndpointName=endpoint_name)
        st.sidebar.info(f"Model endpoint: {ep['EndpointStatus']}")
    except Exception:
        st.sidebar.warning("SageMaker endpoint unavailable")

    c1, c2 = st.columns(2)

    with c1:
        st.subheader("ML Score Distribution")
        dist = _filter(queries.get_ml_score_distribution(date_str))
        if not dist.empty:
            p50 = dist["ml_anomaly_score"].quantile(0.5)
            p90 = dist["ml_anomaly_score"].quantile(0.9)
            fig = px.histogram(dist, x="ml_anomaly_score", color="signal_type",
                               nbins=20, title="Anomaly score distribution")
            fig.add_vline(x=p50, line_dash="dash", annotation_text=f"p50={p50:.2f}")
            fig.add_vline(x=p90, line_dash="dot", annotation_text=f"p90={p90:.2f}")
            st.plotly_chart(fig, use_container_width=True)

    with c2:
        st.subheader("Score vs Signal Strength")
        scatter = _filter(queries.get_ml_score_vs_strength(date_str))
        if not scatter.empty:
            fig = px.scatter(scatter, x="strength", y="ml_anomaly_score",
                             color="signal_type", hover_data=["symbol"],
                             title="ML score vs algorithmic strength")
            st.plotly_chart(fig, use_container_width=True)

    st.subheader("ML-Confirmed Signals (score ≥ 0.75)")
    confirmed = _filter(queries.get_ml_confirmed_signals(date_str, 0.75))
    if not confirmed.empty:
        st.dataframe(confirmed, use_container_width=True)
    else:
        st.info("No ML-confirmed signals today")

