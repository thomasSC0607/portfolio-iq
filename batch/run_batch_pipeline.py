import subprocess
import sys
import boto3
import json
from datetime import datetime

# Configuración
REGION = 'us-east-1'
BUCKET = 'portfolio-iq-datalake'

s3 = boto3.client('s3', region_name=REGION)

def log(msg):
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f"[{timestamp}] {msg}")

def run_script(script_path):
    log(f"Starting: {script_path}")
    result = subprocess.run(
        [sys.executable, script_path],
        capture_output=True,
        text=True
    )
    if result.returncode != 0:
        log(f"ERROR in {script_path}:")
        print(result.stderr)
        return False
    print(result.stdout)
    log(f"Completed: {script_path}")
    return True

def save_execution_log(status, duration_seconds):
    """Guarda un log de la ejecucion en S3 para auditoria"""
    log_entry = {
        'execution_time': datetime.now().isoformat(),
        'status': status,
        'duration_seconds': duration_seconds,
        'scripts_executed': ['data_ingestion.py', 'backtesting.py']
    }
    s3.put_object(
        Bucket=BUCKET,
        Key=f"serving/execution-logs/{datetime.now().strftime('%Y-%m-%d')}.json",
        Body=json.dumps(log_entry, indent=2)
    )
    log(f"Execution log saved to S3")

if __name__ == "__main__":
    log("=== PortfolioIQ Batch Pipeline Started ===")
    start = datetime.now()

    # Paso 1: Ingesta de datos historicos
    ok1 = run_script("batch/data_ingestion.py")
    if not ok1:
        log("Pipeline aborted at ingestion step")
        save_execution_log("FAILED_INGESTION", 0)
        sys.exit(1)

    # Paso 2: Backtesting
    ok2 = run_script("batch/backtesting.py")
    if not ok2:
        log("Pipeline aborted at backtesting step")
        save_execution_log("FAILED_BACKTESTING", 0)
        sys.exit(1)

    duration = (datetime.now() - start).seconds
    save_execution_log("SUCCESS", duration)

    log(f"=== Batch Pipeline Completed in {duration}s ===")