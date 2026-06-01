import streamlit as st
import boto3
import pandas as pd
import json
import io
import plotly.graph_objects as go
import plotly.express as px
from decimal import Decimal
from boto3.dynamodb.conditions import Key

REGION = 'us-east-1'
BUCKET = 'portfolio-iq-datalake'

st.set_page_config(page_title="PortfolioIQ", page_icon="📈", layout="wide")

dynamodb = boto3.resource('dynamodb', region_name=REGION)
s3 = boto3.client('s3', region_name=REGION)

@st.cache_data(ttl=3)
def get_latest_metrics():
    table = dynamodb.Table('portfolio-realtime-metrics')
    symbols = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT']
    latest = {}
    for symbol in symbols:
        response = table.query(
            KeyConditionExpression=Key('asset_id').eq(symbol),
            ScanIndexForward=False,
            Limit=20
        )
        if response['Items']:
            latest[symbol] = response['Items']
    return latest

@st.cache_data(ttl=3)
def get_recent_alerts():
    table = dynamodb.Table('portfolio-alerts')
    response = table.scan(Limit=10)
    items = response.get('Items', [])
    items.sort(key=lambda x: x.get('timestamp', 0), reverse=True)
    return items

@st.cache_data(ttl=60)
def get_backtesting_results():
    try:
        response = s3.get_object(Bucket=BUCKET, Key='processed/batch-results/backtesting_summary.csv')
        return pd.read_csv(io.BytesIO(response['Body'].read()))
    except Exception:
        return None

st.title("📈 PortfolioIQ — Financial Portfolio Intelligence Pipeline")
st.caption("Real-time monitoring (SQS -> DynamoDB) + Batch analytics (S3 -> Backtesting Engine)")
st.divider()

st.header("📡 Real-Time Portfolio Monitor")
metrics_data = get_latest_metrics()

if metrics_data:
    total_pnl = 0
    total_value = 0
    latest_per_symbol = {}
    for symbol, items in metrics_data.items():
        if items:
            item = items[0]
            latest_per_symbol[symbol] = item
            total_pnl += float(item.get('unrealized_pnl', 0))
            total_value += float(item.get('market_value', 0))

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Total Portfolio Value", f"${total_value:,.2f}")
    with col2:
        st.metric("Total Unrealized P&L", f"${total_pnl:,.2f}", delta=f"{'▲' if total_pnl >= 0 else '▼'} {abs(total_pnl):,.2f}")
    with col3:
        st.metric("Assets Monitored", f"{len(latest_per_symbol)}")

    st.divider()
    cols = st.columns(len(latest_per_symbol))
    for i, (symbol, item) in enumerate(latest_per_symbol.items()):
        with cols[i]:
            price = float(item.get('current_price', 0))
            pnl = float(item.get('unrealized_pnl', 0))
            pnl_pct = float(item.get('unrealized_pnl_pct', 0))
            change_24h = float(item.get('price_change_24h_pct', 0))
            vol = float(item.get('rolling_volatility', 0))
            st.subheader(symbol)
            st.metric("Price", f"${price:,.2f}")
            st.metric("Unrealized P&L", f"${pnl:,.2f}", delta=f"{pnl_pct:+.2f}%")
            st.metric("24h Change", f"{change_24h:+.2f}%")
            st.caption(f"Rolling Volatility: {vol:.4f}%")

    st.divider()
    st.subheader("Price History — Retorno Normalizado (Last 20 ticks)")
    fig = go.Figure()
    colors = {'BTCUSDT': '#F7931A', 'ETHUSDT': '#627EEA', 'SOLUSDT': '#9945FF'}
    for symbol, items in metrics_data.items():
        if len(items) > 1:
            items_sorted = sorted(items, key=lambda x: x['timestamp'])
            prices = [float(i['current_price']) for i in items_sorted]
            # Normalizar: retorno porcentual desde el primer precio
            base = prices[0]
            normalized = [((p - base) / base) * 100 for p in prices]
            fig.add_trace(go.Scatter(
                x=list(range(len(normalized))),
                y=normalized,
                mode='lines+markers',
                name=symbol,
                line=dict(color=colors.get(symbol, '#ffffff'), width=2)
            ))
    fig.update_layout(
        template='plotly_dark',
        height=300,
        margin=dict(l=0, r=0, t=30, b=0),
        yaxis_title="Retorno % desde primer tick",
        yaxis_tickformat=".3f",
        legend=dict(orientation='h', y=1.1)
    )
    st.plotly_chart(fig, use_container_width=True)
else:
    st.warning("Waiting for streaming data...")

st.divider()
st.subheader("⚠️ Recent Alerts")
alerts = get_recent_alerts()
if alerts:
    for alert in alerts[:5]:
        severity = alert.get('severity', 'LOW')
        icon = "🔴" if severity == 'HIGH' else "🟡"
        st.write(f"{icon} **{alert.get('symbol')}** — {alert.get('message')} @ ${float(alert.get('current_price', 0)):,.2f}")
else:
    st.info("No alerts fired yet.")

st.divider()
st.header("📊 Batch Analytics — Backtesting Results")
df = get_backtesting_results()
if df is not None:
    st.dataframe(df[['ticker', 'strategy', 'sharpe_ratio', 'cagr', 'max_drawdown', 'total_return', 'win_rate']].round(2), use_container_width=True)
    col1, col2 = st.columns(2)
    with col1:
        fig_sharpe = px.bar(df, x='ticker', y='sharpe_ratio', color='strategy', barmode='group', title='Sharpe Ratio by Asset & Strategy', template='plotly_dark')
        fig_sharpe.update_layout(height=400, margin=dict(l=0, r=0, t=40, b=0))
        st.plotly_chart(fig_sharpe, use_container_width=True)
    with col2:
        fig_cagr = px.bar(df, x='ticker', y='cagr', color='strategy', barmode='group', title='CAGR % by Asset & Strategy', template='plotly_dark')
        fig_cagr.update_layout(height=400, margin=dict(l=0, r=0, t=40, b=0))
        st.plotly_chart(fig_cagr, use_container_width=True)
else:
    st.warning("Batch results not found.")

st.divider()
st.caption("Architecture: Binance WebSocket -> SQS -> Consumer -> DynamoDB (Streaming) | yfinance -> S3 -> Backtesting Engine -> S3 (Batch) | Dashboard: Streamlit on EC2")