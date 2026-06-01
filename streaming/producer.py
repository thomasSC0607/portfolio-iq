import requests
import boto3
import json
import time

REGION = 'us-east-1'
QUEUE_URL = 'https://queue.amazonaws.com/568740658975/portfolio-price-queue'

sqs = boto3.client('sqs', region_name=REGION)

# Mapeo de IDs de CoinGecko a simbolos estandar del sistema
COINS = {
    'bitcoin': 'BTCUSDT',
    'ethereum': 'ETHUSDT',
    'solana': 'SOLUSDT'
}

def fetch_prices():
    """Extrae precios actuales de las tres criptomonedas desde CoinGecko."""
    ids = ','.join(COINS.keys())
    url = (
        f"https://api.coingecko.com/api/v3/simple/price"
        f"?ids={ids}"
        f"&vs_currencies=usd"
        f"&include_24hr_change=true"
        f"&include_24hr_vol=true"
    )
    response = requests.get(url, timeout=10)
    return response.json()

def main():
    print("=== PortfolioIQ Streaming Producer (CoinGecko) ===")
    print(f"Monitoring: {list(COINS.values())}\n")

    while True:
        try:
            data = fetch_prices()
            timestamp = int(time.time() * 1000)

            for coin_id, symbol in COINS.items():
                if coin_id not in data:
                    continue

                coin = data[coin_id]

                # TRANSFORM: estandariza estructura y tipos
                event = {
                    'symbol': symbol,
                    'price': float(coin.get('usd', 0)),
                    'price_change_pct': float(coin.get('usd_24h_change', 0)),
                    'volume': float(coin.get('usd_24h_vol', 0)),
                    'timestamp': timestamp
                }

                # LOAD: publica en SQS
                sqs.send_message(
                    QueueUrl=QUEUE_URL,
                    MessageBody=json.dumps(event)
                )
                print(f"[{symbol}] ${event['price']:,.2f} | 24h: {event['price_change_pct']:+.2f}%")

            # CoinGecko free tier: ~30 calls/min. Esperamos 15s entre polls.
            time.sleep(15)

        except Exception as e:
            print(f"ERROR: {str(e)}")
            time.sleep(30)

if __name__ == "__main__":
    main()