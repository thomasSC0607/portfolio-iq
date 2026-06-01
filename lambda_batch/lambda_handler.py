import subprocess
import sys
import os
import boto3
import json
from datetime import datetime

# En Lambda, el código vive en /var/task
# Configuración
REGION = 'us-east-1'
BUCKET = 'portfolio-iq-datalake'

s3 = boto3.client('s3', region_name=REGION)

def log(msg):
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f"[{timestamp}] {msg}")

def run_ingestion():
    """Descarga datos historicos y los sube a S3"""
    import yfinance as yf
    import pandas as pd
    import io

    ASSETS = ['AAPL', 'MSFT', 'GOOGL', 'AMZN', 'SPY', 'QQQ']
    SECTORS = ['XLK', 'XLF', 'XLE', 'XLV', 'XLU', 'XLI']

    success = 0
    for ticker in ASSETS + SECTORS:
        try:
            df = yf.download(ticker, period='2y', interval='1d', progress=False)
            df.columns = [col[0] if isinstance(col, tuple) else col for col in df.columns]
            df.reset_index(inplace=True)
            df['Date'] = df['Date'].astype(str)

            buf = io.StringIO()
            df.to_csv(buf, index=False)

            s3.put_object(
                Bucket=BUCKET,
                Key=f"raw/market-data/{ticker}/data.csv",
                Body=buf.getvalue()
            )
            log(f"Uploaded {ticker}: {len(df)} rows")
            success += 1
        except Exception as e:
            log(f"ERROR {ticker}: {str(e)}")

    return success

def run_backtesting():
    """Ejecuta backtesting sobre datos en S3"""
    import pandas as pd
    import numpy as np
    import io
    import json

    def load_from_s3(ticker):
        response = s3.get_object(
            Bucket=BUCKET,
            Key=f"raw/market-data/{ticker}/data.csv"
        )
        df = pd.read_csv(io.BytesIO(response['Body'].read()))
        df['Date'] = pd.to_datetime(df['Date'])
        df.set_index('Date', inplace=True)
        return df.sort_index()

    def calculate_metrics(returns, label):
        returns = returns.dropna()
        if len(returns) == 0:
            return {}
        sharpe = (returns.mean() / returns.std()) * np.sqrt(252) if returns.std() > 0 else 0
        cumulative = (1 + returns).cumprod()
        rolling_max = cumulative.cummax()
        drawdown = (cumulative - rolling_max) / rolling_max
        max_drawdown = drawdown.min()
        total_days = len(returns)
        cagr = (cumulative.iloc[-1] ** (252 / total_days)) - 1
        win_rate = len(returns[returns > 0]) / len(returns)
        return {
            'strategy': label,
            'sharpe_ratio': round(float(sharpe), 4),
            'max_drawdown': round(float(max_drawdown) * 100, 2),
            'cagr': round(float(cagr) * 100, 2),
            'total_return': round(float(cumulative.iloc[-1] - 1) * 100, 2),
            'win_rate': round(float(win_rate) * 100, 2)
        }

    def strategy_buy_and_hold(df):
        return calculate_metrics(df['Close'].pct_change().dropna(), 'Buy & Hold')

    def strategy_momentum(df, window=20):
        df = df.copy()
        df['SMA'] = df['Close'].rolling(window=window).mean()
        df['signal'] = (df['Close'] > df['SMA']).shift(1).fillna(False)
        df['daily_return'] = df['Close'].pct_change()
        df['strategy_return'] = df['daily_return'] * df['signal'].astype(int)
        return calculate_metrics(df['strategy_return'].dropna(), f'Momentum SMA-{window}')

    def strategy_mean_reversion(df, window=20, threshold=1.5):
        df = df.copy()
        df['SMA'] = df['Close'].rolling(window=window).mean()
        df['STD'] = df['Close'].rolling(window=window).std()
        df['z_score'] = (df['Close'] - df['SMA']) / df['STD']
        df['signal'] = (df['z_score'] < -threshold).shift(1).fillna(False)
        df['daily_return'] = df['Close'].pct_change()
        df['strategy_return'] = df['daily_return'] * df['signal'].astype(int)
        return calculate_metrics(df['strategy_return'].dropna(), f'Mean Reversion (threshold={threshold})')

    results = {}
    tickers = ['AAPL', 'MSFT', 'GOOGL', 'AMZN', 'SPY', 'QQQ']

    for ticker in tickers:
        try:
            df = load_from_s3(ticker)
            results[ticker] = [
                strategy_buy_and_hold(df),
                strategy_momentum(df, window=20),
                strategy_momentum(df, window=50),
                strategy_mean_reversion(df, window=20, threshold=1.5)
            ]
            log(f"Backtested {ticker}")
        except Exception as e:
            log(f"ERROR backtesting {ticker}: {str(e)}")

    # Guardar JSON
    s3.put_object(
        Bucket=BUCKET,
        Key='processed/batch-results/backtesting_results.json',
        Body=json.dumps(results, indent=2)
    )

    # Guardar CSV para dashboard
    rows = []
    for ticker, strategies in results.items():
        for st in strategies:
            rows.append({'ticker': ticker, **st})

    df_results = pd.DataFrame(rows)
    buf = io.StringIO()
    df_results.to_csv(buf, index=False)
    s3.put_object(
        Bucket=BUCKET,
        Key='processed/batch-results/backtesting_summary.csv',
        Body=buf.getvalue()
    )

    return len(results)

def lambda_handler(event, context):
    """Entry point de AWS Lambda"""
    log("=== PortfolioIQ Lambda Batch Pipeline Started ===")
    start = datetime.now()

    try:
        # Paso 1: Ingesta
        log("Step 1: Data ingestion...")
        assets_uploaded = run_ingestion()
        log(f"Ingestion complete: {assets_uploaded} assets")

        # Paso 2: Backtesting
        log("Step 2: Backtesting...")
        tickers_processed = run_backtesting()
        log(f"Backtesting complete: {tickers_processed} tickers")

        duration = (datetime.now() - start).seconds

        # Log de ejecucion en S3
        s3.put_object(
            Bucket=BUCKET,
            Key=f"serving/execution-logs/{datetime.now().strftime('%Y-%m-%d')}.json",
            Body=json.dumps({
                'execution_time': datetime.now().isoformat(),
                'status': 'SUCCESS',
                'duration_seconds': duration,
                'assets_uploaded': assets_uploaded,
                'tickers_backtested': tickers_processed,
                'trigger': event.get('source', 'manual')
            }, indent=2)
        )

        log(f"=== Pipeline completed in {duration}s ===")
        return {
            'statusCode': 200,
            'body': json.dumps({
                'status': 'SUCCESS',
                'duration_seconds': duration
            })
        }

    except Exception as e:
        log(f"FATAL ERROR: {str(e)}")
        return {
            'statusCode': 500,
            'body': json.dumps({'status': 'ERROR', 'message': str(e)})
        }