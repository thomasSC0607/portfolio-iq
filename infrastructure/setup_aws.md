# Infraestructura AWS — Comandos de Despliegue

## Prerequisitos
- AWS CLI instalado y configurado con credenciales de usuario IAM
- Python 3.11+
- pip

## 1. Crear el Data Lake (S3)

```bash
aws s3api create-bucket --bucket portfolio-iq-datalake --region us-east-1
aws s3api put-object --bucket portfolio-iq-datalake --key raw/market-data/
aws s3api put-object --bucket portfolio-iq-datalake --key processed/batch-results/
aws s3api put-object --bucket portfolio-iq-datalake --key serving/
```

## 2. Crear la Cola SQS

```bash
aws sqs create-queue --queue-name portfolio-price-queue --region us-east-1
```

## 3. Crear Tablas DynamoDB

```bash
aws dynamodb create-table --table-name portfolio-realtime-metrics \
  --attribute-definitions AttributeName=asset_id,AttributeType=S \
    AttributeName=timestamp,AttributeType=N \
  --key-schema AttributeName=asset_id,KeyType=HASH \
    AttributeName=timestamp,KeyType=RANGE \
  --billing-mode PAY_PER_REQUEST --region us-east-1

aws dynamodb create-table --table-name portfolio-alerts \
  --attribute-definitions AttributeName=alert_id,AttributeType=S \
  --key-schema AttributeName=alert_id,KeyType=HASH \
  --billing-mode PAY_PER_REQUEST --region us-east-1
```

## 4. Desplegar Lambda

```bash
# Instalar dependencias para Linux
pip install yfinance pandas numpy boto3 --target ./lambda_linux/package \
  --platform manylinux2014_x86_64 --implementation cp \
  --python-version 3.11 --only-binary=:all:

# Empaquetar
cd lambda_linux/package
Compress-Archive -Path * -DestinationPath ../lambda_linux.zip -Force
cd ../..

# Crear rol IAM
aws iam create-role --role-name portfolio-iq-lambda-role \
  --assume-role-policy-document file://infrastructure/lambda-trust-policy.json

aws iam attach-role-policy --role-name portfolio-iq-lambda-role \
  --policy-arn arn:aws:iam::aws:policy/AmazonS3FullAccess

aws iam attach-role-policy --role-name portfolio-iq-lambda-role \
  --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole

# Subir a S3 y desplegar
aws s3 cp lambda_linux/lambda_linux.zip s3://portfolio-iq-datalake/lambda/lambda_linux.zip

aws lambda create-function --function-name portfolio-iq-batch-pipeline \
  --runtime python3.11 --handler lambda_handler.lambda_handler \
  --role arn:aws:iam::TU_ACCOUNT_ID:role/portfolio-iq-lambda-role \
  --code S3Bucket=portfolio-iq-datalake,S3Key=lambda/lambda_linux.zip \
  --timeout 900 --memory-size 512 --region us-east-1
```

## 5. Crear el Scheduler (EventBridge)

```bash
aws scheduler create-schedule --name portfolio-iq-nightly-batch \
  --schedule-expression "cron(0 7 * * ? *)" \
  --target file://infrastructure/scheduler-target.json \
  --flexible-time-window file://infrastructure/scheduler-window.json \
  --region us-east-1
```

## 6. Lanzar EC2

```bash
aws ec2 create-security-group \
  --group-name portfolio-iq-sg \
  --description "PortfolioIQ security group"

aws ec2 authorize-security-group-ingress \
  --group-name portfolio-iq-sg --protocol tcp --port 22 --cidr 0.0.0.0/0

aws ec2 authorize-security-group-ingress \
  --group-name portfolio-iq-sg --protocol tcp --port 8501 --cidr 0.0.0.0/0

aws ec2 run-instances \
  --image-id ami-0c02fb55956c7d316 \
  --instance-type t3.micro \
  --key-name portfolio-iq-key \
  --security-groups portfolio-iq-sg \
  --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=portfolio-iq-server}]"
```

## 7. Configurar Servicios en EC2

Conectarse via EC2 Instance Connect y ejecutar:

```bash
sudo yum update -y
sudo yum install python3-pip -y
pip3 install boto3 yfinance pandas numpy websockets streamlit plotly requests

# Copiar scripts al servidor y crear servicios systemd
sudo systemctl enable portfolio-producer portfolio-consumer portfolio-dashboard
sudo systemctl start portfolio-producer portfolio-consumer portfolio-dashboard
```

## Verificar despliegue

```bash
# Estado de servicios
sudo systemctl status portfolio-producer portfolio-consumer portfolio-dashboard

# Probar Lambda manualmente
aws lambda invoke --function-name portfolio-iq-batch-pipeline \
  --region us-east-1 response.json
cat response.json

# Verificar datos en S3
aws s3 ls s3://portfolio-iq-datalake/processed/batch-results/
```