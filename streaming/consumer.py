import boto3
import json
import time
from decimal import Decimal
from datetime import datetime

# Configuración
REGION = 'us-east-1'
QUEUE_URL = 'https://queue.amazonaws.com/568740658975/portfolio-price-queue'

sqs = boto3.client('sqs', region_name=REGION)
dynamodb = boto3.resource('dynamodb', region_name=REGION)

metrics_table = dynamodb.Table('portfolio-realtime-metrics')
alerts_table = dynamodb.Table('portfolio-alerts')

# Portafolio simulado
PORTFOLIO = {
    'BTCUSDT': {'units': 0.5,  'avg_cost': 60000},
    'ETHUSDT': {'units': 3.0,  'avg_cost': 3200},
    'SOLUSDT': {'units': 20.0, 'avg_cost': 140}
}

# Reglas de alerta
ALERT_RULES = {
    'price_drop_threshold': -3.0,
    'price_rise_threshold':  5.0
}

# Historial en memoria para volatilidad rolling
price_history = {}

def calculate_rolling_volatility(symbol, new_price):
    if symbol not in price_history:
        price_history[symbol] = []

    price_history[symbol].append(new_price)

    if len(price_history[symbol]) > 20:
        price_history[symbol].pop(0)

    if len(price_history[symbol]) < 2:
        return 0.0

    prices = price_history[symbol]
    returns = [(prices[i] - prices[i-1]) / prices[i-1]
               for i in range(1, len(prices))]
    mean = sum(returns) / len(returns)
    variance = sum((r - mean) ** 2 for r in returns) / len(returns)
    return (variance ** 0.5) * 100

def process_event(event):
    symbol = event['symbol']
    current_price = event['price']
    price_change_pct = event['price_change_pct']
    timestamp = event['timestamp']

    if symbol not in PORTFOLIO:
        return

    position = PORTFOLIO[symbol]
    units = position['units']
    avg_cost = position['avg_cost']

    market_value = units * current_price
    cost_basis = units * avg_cost
    unrealized_pnl = market_value - cost_basis
    unrealized_pnl_pct = (unrealized_pnl / cost_basis) * 100
    rolling_vol = calculate_rolling_volatility(symbol, current_price)

    # Guardar métricas en DynamoDB
    metrics_table.put_item(Item={
        'asset_id': symbol,
        'timestamp': timestamp,
        'current_price': Decimal(str(round(current_price, 2))),
        'market_value': Decimal(str(round(market_value, 2))),
        'unrealized_pnl': Decimal(str(round(unrealized_pnl, 2))),
        'unrealized_pnl_pct': Decimal(str(round(unrealized_pnl_pct, 4))),
        'rolling_volatility': Decimal(str(round(rolling_vol, 4))),
        'price_change_24h_pct': Decimal(str(round(price_change_pct, 4)))
    })

    print(f"[{symbol}] Price: ${current_price:>10,.2f} | "
          f"P&L: ${unrealized_pnl:>+8.2f} ({unrealized_pnl_pct:+.2f}%) | "
          f"Vol: {rolling_vol:.4f}%")

    # Evaluar alertas
    if price_change_pct <= ALERT_RULES['price_drop_threshold']:
        alert_id = f"{symbol}_{timestamp}"
        alerts_table.put_item(Item={
            'alert_id': alert_id,
            'symbol': symbol,
            'alert_type': 'PRICE_DROP',
            'message': f"{symbol} cayó {price_change_pct:.2f}% en 24h",
            'current_price': Decimal(str(round(current_price, 2))),
            'timestamp': timestamp,
            'severity': 'HIGH'
        })
        print(f"  ⚠️  ALERT FIRED: {symbol} drop {price_change_pct:.2f}%")

    elif price_change_pct >= ALERT_RULES['price_rise_threshold']:
        alert_id = f"{symbol}_{timestamp}"
        alerts_table.put_item(Item={
            'alert_id': alert_id,
            'symbol': symbol,
            'alert_type': 'PRICE_RISE',
            'message': f"{symbol} subió {price_change_pct:.2f}% en 24h",
            'current_price': Decimal(str(round(current_price, 2))),
            'timestamp': timestamp,
            'severity': 'MEDIUM'
        })
        print(f"  🚀  ALERT FIRED: {symbol} rise {price_change_pct:.2f}%")

def poll_sqs():
    print("=== PortfolioIQ Streaming Consumer ===")
    print(f"Polling SQS queue...\n")

    while True:
        response = sqs.receive_message(
            QueueUrl=QUEUE_URL,
            MaxNumberOfMessages=10,
            WaitTimeSeconds=5  # Long polling — más eficiente
        )

        messages = response.get('Messages', [])

        if not messages:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Waiting for messages...")
            continue

        for message in messages:
            event = json.loads(message['Body'])
            process_event(event)

            # Eliminar el mensaje procesado de la cola
            sqs.delete_message(
                QueueUrl=QUEUE_URL,
                ReceiptHandle=message['ReceiptHandle']
            )

if __name__ == "__main__":
    poll_sqs()