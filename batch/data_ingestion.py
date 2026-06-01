import yfinance as yf
import boto3
import pandas as pd
from datetime import datetime
import io

# Configuración
BUCKET = 'portfolio-iq-datalake'
REGION = 'us-east-1'

s3 = boto3.client('s3', region_name=REGION)

# Activos del portafolio
ASSETS = ['AAPL', 'MSFT', 'GOOGL', 'AMZN', 'SPY', 'QQQ']

# ETFs sectoriales para análisis de rotación
SECTORS = ['XLK', 'XLF', 'XLE', 'XLV', 'XLU', 'XLI']

def download_and_upload(ticker, period='2y'):
    print(f"Downloading {ticker}...")
    
    df = yf.download(ticker, period=period, interval='1d', progress=False)
    
    if df.empty:
        print(f"WARNING: No data for {ticker}")
        return False
    
    # Aplanar columnas multi-index que genera yfinance
    df.columns = [col[0] if isinstance(col, tuple) else col for col in df.columns]
    df.reset_index(inplace=True)
    df['Date'] = df['Date'].astype(str)
    
    # Subir a S3
    csv_buffer = io.StringIO()
    df.to_csv(csv_buffer, index=False)
    
    key = f"raw/market-data/{ticker}/data.csv"
    s3.put_object(
        Bucket=BUCKET,
        Key=key,
        Body=csv_buffer.getvalue()
    )
    
    print(f"Uploaded {ticker}: {len(df)} rows -> s3://{BUCKET}/{key}")
    return True

if __name__ == "__main__":
    print("=== Starting batch data ingestion ===")
    print(f"Timestamp: {datetime.now()}\n")
    
    all_tickers = ASSETS + SECTORS
    success = 0
    
    for ticker in all_tickers:
        if download_and_upload(ticker):
            success += 1
    
    print(f"\n=== Ingestion complete: {success}/{len(all_tickers)} assets uploaded ===")