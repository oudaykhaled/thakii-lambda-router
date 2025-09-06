#!/bin/bash

# AWS Lambda Deployment Script for AI Service Router
set -e

echo "🚀 Deploying AI Service Router to AWS Lambda..."

# Configuration
FUNCTION_NAME="thakii-ai-service-router"
RUNTIME="python3.9"
HANDLER="lambda_function.lambda_handler"
TIMEOUT=300
MEMORY_SIZE=512
REGION="us-east-2"

# Create deployment package
echo "📦 Creating deployment package..."

# Clean previous builds
rm -rf package/
rm -f deployment.zip

# Create package directory
mkdir -p package

# Install dependencies
pip install -r requirements.txt -t package/

# Copy function code and config
cp lambda_function.py package/
cp config.json package/

# Create zip file
cd package
zip -r ../deployment.zip .
cd ..

echo "✅ Deployment package created: deployment.zip"

# Check if function exists
if aws lambda get-function --function-name $FUNCTION_NAME --region $REGION >/dev/null 2>&1; then
    echo "🔄 Updating existing Lambda function..."
    aws lambda update-function-code \
        --function-name $FUNCTION_NAME \
        --zip-file fileb://deployment.zip \
        --region $REGION
    
    aws lambda update-function-configuration \
        --function-name $FUNCTION_NAME \
        --runtime $RUNTIME \
        --handler $HANDLER \
        --timeout $TIMEOUT \
        --memory-size $MEMORY_SIZE \
        --region $REGION
else
    echo "🆕 Creating new Lambda function..."
    aws lambda create-function \
        --function-name $FUNCTION_NAME \
        --runtime $RUNTIME \
        --role arn:aws:iam::$(aws sts get-caller-identity --query Account --output text):role/lambda-execution-role \
        --handler $HANDLER \
        --zip-file fileb://deployment.zip \
        --timeout $TIMEOUT \
        --memory-size $MEMORY_SIZE \
        --region $REGION
fi

# Create API Gateway if it doesn't exist
echo "🌐 Setting up API Gateway..."

# Get or create API Gateway
API_ID=$(aws apigateway get-rest-apis --region $REGION --query "items[?name=='thakii-ai-router-api'].id" --output text)

if [ "$API_ID" = "None" ] || [ -z "$API_ID" ]; then
    echo "🆕 Creating new API Gateway..."
    API_ID=$(aws apigateway create-rest-api \
        --name "thakii-ai-router-api" \
        --description "AI Service Router API" \
        --region $REGION \
        --query 'id' --output text)
fi

echo "📡 API Gateway ID: $API_ID"

# Get root resource ID
ROOT_RESOURCE_ID=$(aws apigateway get-resources \
    --rest-api-id $API_ID \
    --region $REGION \
    --query 'items[?path==`/`].id' --output text)

# Create proxy resource if it doesn't exist
PROXY_RESOURCE_ID=$(aws apigateway get-resources \
    --rest-api-id $API_ID \
    --region $REGION \
    --query 'items[?pathPart==`{proxy+}`].id' --output text 2>/dev/null || echo "")

if [ -z "$PROXY_RESOURCE_ID" ] || [ "$PROXY_RESOURCE_ID" = "None" ]; then
    echo "🔗 Creating proxy resource..."
    PROXY_RESOURCE_ID=$(aws apigateway create-resource \
        --rest-api-id $API_ID \
        --parent-id $ROOT_RESOURCE_ID \
        --path-part '{proxy+}' \
        --region $REGION \
        --query 'id' --output text)
fi

# Create ANY method for proxy resource
aws apigateway put-method \
    --rest-api-id $API_ID \
    --resource-id $PROXY_RESOURCE_ID \
    --http-method ANY \
    --authorization-type NONE \
    --region $REGION >/dev/null 2>&1 || echo "Method already exists"

# Set up Lambda integration
LAMBDA_ARN="arn:aws:lambda:$REGION:$(aws sts get-caller-identity --query Account --output text):function:$FUNCTION_NAME"

aws apigateway put-integration \
    --rest-api-id $API_ID \
    --resource-id $PROXY_RESOURCE_ID \
    --http-method ANY \
    --type AWS_PROXY \
    --integration-http-method POST \
    --uri "arn:aws:apigateway:$REGION:lambda:path/2015-03-31/functions/$LAMBDA_ARN/invocations" \
    --region $REGION >/dev/null 2>&1 || echo "Integration already exists"

# Add Lambda permission for API Gateway
aws lambda add-permission \
    --function-name $FUNCTION_NAME \
    --statement-id "api-gateway-invoke" \
    --action "lambda:InvokeFunction" \
    --principal "apigateway.amazonaws.com" \
    --source-arn "arn:aws:apigateway:$REGION::/restapis/$API_ID/*" \
    --region $REGION >/dev/null 2>&1 || echo "Permission already exists"

# Deploy API
echo "🚀 Deploying API Gateway..."
aws apigateway create-deployment \
    --rest-api-id $API_ID \
    --stage-name "prod" \
    --region $REGION >/dev/null

# Get API endpoint
API_ENDPOINT="https://$API_ID.execute-api.$REGION.amazonaws.com/prod"

echo ""
echo "✅ Deployment completed successfully!"
echo ""
echo "📊 Deployment Summary:"
echo "   Lambda Function: $FUNCTION_NAME"
echo "   API Gateway ID: $API_ID"
echo "   API Endpoint: $API_ENDPOINT"
echo ""
echo "🧪 Test your API:"
echo "   curl -X GET $API_ENDPOINT/health"
echo ""
echo "📝 Update your client applications to use: $API_ENDPOINT" 