import boto3
import pandas as pd
import numpy as np
import json
import io
from datetime import datetime

# Configuración
BUCKET = 'portfolio-iq-datalake'
REGION = 'us-east-1'

s3 = boto3.client('s3', region_name=REGION)

def load_from_s3(ticker):
    response = s3.get_object(
        Bucket=BUCKET,
        Key=f"raw/market-data/{ticker}/data.csv"
    )
    df = pd.read_csv(io.BytesIO(response['Body'].read()))
    df['Date'] = pd.to_datetime(df['Date'])
    df.set_index('Date', inplace=True)
    df = df.sort_index()
    return df

def calculate_metrics(returns, label):
    returns = returns.dropna()
    
    if len(returns) == 0:
        return {}

    # Sharpe Ratio anualizado
    sharpe = (returns.mean() / returns.std()) * np.sqrt(252) if returns.std() > 0 else 0

    # Cumulative returns
    cumulative = (1 + returns).cumprod()

    # Max Drawdown
    rolling_max = cumulative.cummax()
    drawdown = (cumulative - rolling_max) / rolling_max
    max_drawdown = drawdown.min()

    # CAGR
    total_days = len(returns)
    final_value = cumulative.iloc[-1]
    cagr = (final_value ** (252 / total_days)) - 1

    # Win rate
    win_rate = len(returns[returns > 0]) / len(returns)

    # Total return
    total_return = final_value - 1

    return {
        'strategy': label,
        'sharpe_ratio': round(float(sharpe), 4),
        'max_drawdown': round(float(max_drawdown) * 100, 2),
        'cagr': round(float(cagr) * 100, 2),
        'total_return': round(float(total_return) * 100, 2),
        'win_rate': round(float(win_rate) * 100, 2),
        'total_trading_days': total_days
    }

def strategy_buy_and_hold(df):
    """
    Baseline: compra en el primer día y mantiene hasta el final.
    Retorno diario = variación porcentual del precio de cierre.
    """
    returns = df['Close'].pct_change().dropna()
    return calculate_metrics(returns, 'Buy & Hold')

def strategy_momentum(df, window=20):
    """
    Momentum: estar invertido solo cuando el precio está
    por encima de su SMA de N días.
    
    shift(1) es crítico: la decisión de HOY usa la SMA
    calculada hasta AYER. Así evitamos look-ahead bias —
    no usamos información del futuro para decidir en el pasado.
    """
    df = df.copy()
    df['SMA'] = df['Close'].rolling(window=window).mean()
    df['signal'] = (df['Close'] > df['SMA']).shift(1).fillna(False)
    df['daily_return'] = df['Close'].pct_change()
    df['strategy_return'] = df['daily_return'] * df['signal'].astype(int)
    
    return calculate_metrics(
        df['strategy_return'].dropna(),
        f'Momentum SMA-{window}'
    )

def strategy_mean_reversion(df, window=20, threshold=1.5):
    """
    Mean Reversion: compra cuando el precio está significativamente
    por debajo de su media (oportunidad de rebote).
    
    Señal: precio actual está más de N desviaciones estándar
    por debajo de la SMA → esperamos que revierta a la media.
    
    shift(1) aplicado por la misma razón que en momentum.
    """
    df = df.copy()
    df['SMA'] = df['Close'].rolling(window=window).mean()
    df['STD'] = df['Close'].rolling(window=window).std()
    df['z_score'] = (df['Close'] - df['SMA']) / df['STD']
    df['signal'] = (df['z_score'] < -threshold).shift(1).fillna(False)
    df['daily_return'] = df['Close'].pct_change()
    df['strategy_return'] = df['daily_return'] * df['signal'].astype(int)
    
    return calculate_metrics(
        df['strategy_return'].dropna(),
        f'Mean Reversion (threshold={threshold})'
    )

def run_backtesting(tickers):
    all_results = {}

    for ticker in tickers:
        print(f"Backtesting {ticker}...")
        try:
            df = load_from_s3(ticker)

            results = [
                strategy_buy_and_hold(df),
                strategy_momentum(df, window=20),
                strategy_momentum(df, window=50),
                strategy_mean_reversion(df, window=20, threshold=1.5)
            ]

            all_results[ticker] = results
            
            # Print resultado rápido en consola
            for r in results:
                print(f"  {r['strategy']:35s} | "
                      f"Sharpe: {r['sharpe_ratio']:6.3f} | "
                      f"CAGR: {r['cagr']:7.2f}% | "
                      f"Max DD: {r['max_drawdown']:7.2f}%")

        except Exception as e:
            print(f"  ERROR: {str(e)}")

    return all_results

def save_results(results):
    # Guardar JSON completo
    s3.put_object(
        Bucket=BUCKET,
        Key='processed/batch-results/backtesting_results.json',
        Body=json.dumps(results, indent=2)
    )

    # Guardar CSV plano para el dashboard
    rows = []
    for ticker, strategies in results.items():
        for s in strategies:
            rows.append({'ticker': ticker, **s})

    df = pd.DataFrame(rows)
    csv_buffer = io.StringIO()
    df.to_csv(csv_buffer, index=False)

    s3.put_object(
        Bucket=BUCKET,
        Key='processed/batch-results/backtesting_summary.csv',
        Body=csv_buffer.getvalue()
    )

    print(f"\nResults saved to s3://{BUCKET}/processed/batch-results/")

if __name__ == "__main__":
    print("=== Starting Backtesting Engine ===")
    print(f"Timestamp: {datetime.now()}\n")

    TICKERS = ['AAPL', 'MSFT', 'GOOGL', 'AMZN', 'SPY', 'QQQ']

    results = run_backtesting(TICKERS)
    save_results(results)

    print("\n=== Backtesting complete ===")