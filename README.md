# Thakii Lambda Router

AWS Lambda-based load balancer and API gateway for the Thakii Lecture2PDF Service. Provides intelligent routing, circuit breaking, and high availability for backend services.

## 🚀 Features

- **Intelligent Load Balancing**: Priority-based routing with health monitoring
- **Circuit Breaker Pattern**: Automatic failure detection and recovery
- **Multi-Backend Support**: Route requests to multiple backend instances
- **Health Monitoring**: Continuous health checks and status tracking
- **Fallback Mechanisms**: Automatic failover to backup services
- **Request Forwarding**: Transparent proxy with full request/response support
- **Configurable Routing**: JSON-based service configuration

## 🛠️ Technology Stack

- **AWS Lambda**: Serverless compute platform
- **AWS API Gateway**: HTTP API management
- **Python 3.9**: Runtime environment
- **Requests Library**: HTTP client for backend communication

## 📁 Project Structure

```
thakii-lambda-router/
├── src/
│   ├── lambda_function.py        # Main Lambda handler
│   ├── service_manager.py        # Load balancing logic
│   ├── circuit_breaker.py        # Circuit breaker implementation
│   └── health_monitor.py         # Health checking
├── config/
│   ├── services.json            # Backend service configuration
│   └── routing_rules.json       # Routing rules
├── deployment/
│   ├── terraform/               # Infrastructure as Code
│   ├── cloudformation/          # Alternative IaC
│   └── deploy.sh               # Deployment script
├── tests/
└── requirements.txt
```

## ⚙️ Configuration

### Service Configuration (`config/services.json`)
```json
{
  "ai_services": [
    {
      "name": "primary-backend",
      "url": "https://api.primary.thakii.com",
      "priority": 1,
      "timeout": 300,
      "enabled": true,
      "health_check_path": "/health"
    },
    {
      "name": "secondary-backend", 
      "url": "https://api.secondary.thakii.com",
      "priority": 2,
      "timeout": 300,
      "enabled": true,
      "health_check_path": "/health"
    }
  ],
  "circuit_breaker": {
    "failure_threshold": 5,
    "recovery_timeout": 60,
    "half_open_max_calls": 3
  },
  "load_balancing": {
    "strategy": "priority",
    "health_check_interval": 30,
    "timeout": 30
  }
}
```

## 🚀 Deployment

### Prerequisites
- AWS CLI configured
- IAM permissions for Lambda, API Gateway, and CloudWatch
- Python 3.9+ for local development

### Quick Deploy
```bash
# Clone repository
git clone https://github.com/oudaykhaled/thakii-lambda-router.git
cd thakii-lambda-router

# Deploy with script
./deployment/deploy.sh
```

### Manual Deployment
```bash
# Install dependencies
pip install -r requirements.txt -t package/

# Create deployment package
cd package/
zip -r ../deployment.zip .
cd ..
zip -g deployment.zip src/*.py config/*.json

# Create Lambda function
aws lambda create-function \
  --function-name thakii-router \
  --runtime python3.9 \
  --handler src.lambda_function.lambda_handler \
  --zip-file fileb://deployment.zip \
  --role arn:aws:iam::ACCOUNT:role/lambda-execution-role
```

### Terraform Deployment
```bash
cd deployment/terraform
terraform init
terraform plan
terraform apply
```

## 📡 API Gateway Integration

### Route Configuration
```yaml
# API Gateway routes (all proxy to Lambda)
ANY /{proxy+}
  Integration: Lambda Proxy
  Lambda Function: thakii-router
  
# Health check endpoint
GET /health
  Integration: Lambda Proxy
  Lambda Function: thakii-router
```

### CORS Configuration
```json
{
  "allowCredentials": true,
  "allowHeaders": ["*"],
  "allowMethods": ["*"],
  "allowOrigins": ["https://app.thakii.com", "http://localhost:3000"],
  "maxAge": 86400
}
```

## 🔄 Load Balancing Strategies

### Priority-Based Routing (Default)
```python
# Routes to highest priority available service
services = [
  {"priority": 1, "name": "primary"},    # Try first
  {"priority": 2, "name": "secondary"}   # Fallback
]
```

### Round-Robin Routing
```python
# Distributes requests evenly across available services
config = {
  "load_balancing": {
    "strategy": "round_robin",
    "round_robin_enabled": true
  }
}
```

### Weighted Routing
```python
# Routes based on service weights
services = [
  {"weight": 70, "name": "primary"},
  {"weight": 30, "name": "secondary"}
]
```

## 🔧 Circuit Breaker Implementation

### Circuit States
```python
# CLOSED: Normal operation, requests pass through
# OPEN: Service failed, requests immediately rejected
# HALF-OPEN: Testing recovery, limited requests allowed

class CircuitBreaker:
    def __init__(self, failure_threshold=5, recovery_timeout=60):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.failure_count = 0
        self.last_failure_time = 0
        self.state = 'CLOSED'
```

### Failure Detection
```python
def record_failure(service_name):
    circuit_data = circuit_breakers.get(service_name, {
        'failures': 0,
        'last_failure': 0,
        'state': 'closed'
    })
    
    circuit_data['failures'] += 1
    circuit_data['last_failure'] = time.time()
    
    if circuit_data['failures'] >= failure_threshold:
        circuit_data['state'] = 'open'
        logger.warning(f"Circuit breaker opened for {service_name}")
```

## 📊 Monitoring & Logging

### CloudWatch Metrics
```python
# Custom metrics published to CloudWatch
metrics = {
    'RequestCount': len(requests),
    'SuccessRate': success_count / total_requests,
    'AverageLatency': sum(latencies) / len(latencies),
    'CircuitBreakerTrips': circuit_breaker_trips,
    'HealthyServices': len(healthy_services)
}
```

### Structured Logging
```python
logger.info(f"Routing request to {service_name}", extra={
    'service': service_name,
    'method': method,
    'path': path,
    'latency': response_time,
    'status_code': status_code
})
```

## 🧪 Testing

### Local Testing
```bash
# Install test dependencies
pip install pytest pytest-mock boto3

# Run unit tests
python -m pytest tests/

# Run integration tests
python -m pytest tests/integration/
```

### Load Testing
```bash
# Using Artillery.js
npm install -g artillery
artillery quick --count 100 --num 10 https://api-gateway-url.com/health

# Using curl for simple testing
for i in {1..100}; do
  curl -s https://api-gateway-url.com/health > /dev/null &
done
wait
```

## 🔒 Security Features

### IAM Permissions
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "logs:CreateLogGroup",
        "logs:CreateLogStream", 
        "logs:PutLogEvents"
      ],
      "Resource": "arn:aws:logs:*:*:*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "cloudwatch:PutMetricData"
      ],
      "Resource": "*"
    }
  ]
}
```

### Request Validation
```python
def validate_request(event):
    # Validate HTTP method
    if event['httpMethod'] not in ['GET', 'POST', 'PUT', 'DELETE']:
        return False
    
    # Validate path
    path = event.get('path', '')
    if not path or len(path) > 1000:
        return False
    
    return True
```

## 📈 Performance Optimization

### Cold Start Mitigation
```python
# Global variables for connection reuse
import requests
session = requests.Session()

# Connection pooling
session.mount('https://', requests.adapters.HTTPAdapter(
    pool_connections=10,
    pool_maxsize=20
))
```

### Timeout Configuration
```python
# Aggressive timeouts for better user experience
TIMEOUTS = {
    'connect': 5,      # Connection timeout
    'read': 25,        # Read timeout  
    'total': 30        # Total request timeout
}
```

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/new-feature`
3. Install dependencies: `pip install -r requirements.txt`
4. Make changes and add tests
5. Run tests: `pytest`
6. Deploy to test environment
7. Submit a pull request

## 📄 License

This project is licensed under the MIT License - see the LICENSE file for details.

## 🔗 Related Repositories

- [thakii-backend-api](https://github.com/oudaykhaled/thakii-backend-api) - Backend services
- [thakii-frontend](https://github.com/oudaykhaled/thakii-frontend) - Frontend application
- [thakii-infrastructure](https://github.com/oudaykhaled/thakii-infrastructure) - Infrastructure as Code
