import json
import requests
import time
import random
import os
from typing import List, Dict, Optional, Tuple
import logging

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

class ServiceManager:
    def __init__(self, config: Dict):
        self.config = config
        self.services = config.get('ai_services', [])
        self.circuit_breakers = {}
        self.last_health_check = {}
        
    def get_available_services(self) -> List[Dict]:
        """Get list of enabled and available services sorted by priority"""
        available = []
        current_time = time.time()
        
        for service in self.services:
            if not service.get('enabled', True):
                continue
                
            service_name = service['name']
            
            # Check circuit breaker status
            if self._is_circuit_breaker_open(service_name, current_time):
                logger.warning(f"Service {service_name} circuit breaker is open")
                continue
                
            available.append(service)
        
        # Sort by priority (lower number = higher priority)
        return sorted(available, key=lambda x: x.get('priority', 999))
    
    def _is_circuit_breaker_open(self, service_name: str, current_time: float) -> bool:
        """Check if circuit breaker is open for a service"""
        cb_config = self.config.get('circuit_breaker', {})
        failure_threshold = cb_config.get('failure_threshold', 5)
        recovery_timeout = cb_config.get('recovery_timeout', 60)
        
        cb_state = self.circuit_breakers.get(service_name, {'failures': 0, 'last_failure': 0})
        
        if cb_state['failures'] >= failure_threshold:
            if current_time - cb_state['last_failure'] < recovery_timeout:
                return True
            else:
                # Reset circuit breaker after recovery timeout
                self.circuit_breakers[service_name] = {'failures': 0, 'last_failure': 0}
        
        return False
    
    def record_failure(self, service_name: str):
        """Record a failure for circuit breaker tracking"""
        current_time = time.time()
        if service_name not in self.circuit_breakers:
            self.circuit_breakers[service_name] = {'failures': 0, 'last_failure': 0}
        
        self.circuit_breakers[service_name]['failures'] += 1
        self.circuit_breakers[service_name]['last_failure'] = current_time
        
        logger.warning(f"Recorded failure for {service_name}. Total failures: {self.circuit_breakers[service_name]['failures']}")
    
    def record_success(self, service_name: str):
        """Record a success and reset circuit breaker if needed"""
        if service_name in self.circuit_breakers:
            self.circuit_breakers[service_name]['failures'] = 0
        logger.info(f"Recorded success for {service_name}")

def load_config() -> Dict:
    """Load configuration from config.json"""
    # Prefer layer path /opt, then local dir, then package path
    candidate_paths = [
        os.environ.get('ROUTER_CONFIG_PATH'),
        '/opt/config.json',
        os.path.join(os.path.dirname(__file__), 'config.json')
    ]
    for path in candidate_paths:
        if not path:
            continue
        try:
            with open(path, 'r') as f:
                cfg = json.load(f)
                logger.info(f"Loaded config from {path}")
                return cfg
        except FileNotFoundError:
            continue
        except Exception as e:
            logger.error(f"Failed to load config from {path}: {e}")
            continue
    # Fallback configuration
    logger.warning("Config file not found, using fallback configuration")
    return {
        "ai_services": [
            {
                "name": "ngrok-local",
                "url": "http://localhost:5001",
                "priority": 1,
                "timeout": 300,
                "enabled": True
            }
        ],
        "default_timeout": 300,
        "max_retries": 3
    }

def health_check_service(service: Dict) -> bool:
    """Check if a service is healthy"""
    try:
        response = requests.get(
            f"{service['url']}/health",
            timeout=5
        )
        return response.status_code == 200
    except Exception as e:
        logger.error(f"Health check failed for {service['name']}: {str(e)}")
        return False

def forward_request(service: Dict, path: str, method: str, headers: Dict, data: bytes = None, files: Dict = None) -> Tuple[int, Dict, bytes]:
    """Forward request to a specific service"""
    try:
        url = f"{service['url']}{path}"
        timeout = service.get('timeout', 300)
        
        # Prepare headers (exclude hop-by-hop headers)
        forwarded_headers = {}
        for key, value in headers.items():
            if key.lower() not in ['host', 'connection', 'content-length']:
                forwarded_headers[key] = value
        
        logger.info(f"Forwarding {method} request to {service['name']}: {url}")
        
        if method == 'GET':
            response = requests.get(url, headers=forwarded_headers, timeout=timeout)
        elif method == 'POST':
            if files:
                response = requests.post(url, headers=forwarded_headers, files=files, timeout=timeout)
            else:
                response = requests.post(url, headers=forwarded_headers, data=data, timeout=timeout)
        elif method == 'PUT':
            response = requests.put(url, headers=forwarded_headers, data=data, timeout=timeout)
        elif method == 'DELETE':
            response = requests.delete(url, headers=forwarded_headers, timeout=timeout)
        else:
            return 405, {}, b'Method not allowed'
        
        # Extract response headers
        response_headers = {}
        for key, value in response.headers.items():
            if key.lower() not in ['connection', 'transfer-encoding']:
                response_headers[key] = value
        
        logger.info(f"Service {service['name']} responded with status {response.status_code}")
        return response.status_code, response_headers, response.content
        
    except requests.exceptions.Timeout:
        logger.error(f"Timeout when forwarding request to {service['name']}")
        return 504, {}, b'Gateway timeout'
    except requests.exceptions.ConnectionError:
        logger.error(f"Connection error when forwarding request to {service['name']}")
        return 503, {}, b'Service unavailable'
    except Exception as e:
        logger.error(f"Error forwarding request to {service['name']}: {str(e)}")
        return 500, {}, b'Internal server error'

def lambda_handler(event, context):
    """Main Lambda handler function"""
    try:
        # Load configuration
        config = load_config()
        service_manager = ServiceManager(config)
        
        # Extract request information
        http_method = event.get('httpMethod', 'GET')
        path = event.get('path', '/')
        headers = event.get('headers', {})
        query_params = event.get('queryStringParameters') or {}
        
        # Handle body for POST requests
        body = None
        files = None
        if event.get('body'):
            if event.get('isBase64Encoded'):
                import base64
                body = base64.b64decode(event['body'])
            else:
                body = event['body'].encode('utf-8')
        
        logger.info(f"Received {http_method} request for path: {path}")
        
        # Get available services
        available_services = service_manager.get_available_services()
        
        if not available_services:
            logger.error("No available services found")
            return {
                'statusCode': 503,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': json.dumps({
                    'error': 'Service not reachable at this moment',
                    'message': 'All AI services are currently unavailable. Please try again later.',
                    'timestamp': time.time()
                })
            }
        
        # Try each service in priority order
        last_error = None
        for service in available_services:
            logger.info(f"Trying service: {service['name']} ({service['url']})")
            
            # Perform health check for critical endpoints
            if path in ['/upload', '/download'] and not health_check_service(service):
                logger.warning(f"Health check failed for {service['name']}, skipping")
                service_manager.record_failure(service['name'])
                continue
            
            # Forward the request
            status_code, response_headers, response_body = forward_request(
                service, path, http_method, headers, body, files
            )
            
            # Check if request was successful
            if status_code < 400:
                service_manager.record_success(service['name'])
                
                # Prepare Lambda response
                response = {
                    'statusCode': status_code,
                    'headers': response_headers,
                    'body': response_body.decode('utf-8') if response_body else ''
                }
                
                # Handle binary responses
                if any(content_type in response_headers.get('content-type', '').lower() 
                       for content_type in ['application/pdf', 'image/', 'video/', 'audio/']):
                    import base64
                    response['body'] = base64.b64encode(response_body).decode('utf-8')
                    response['isBase64Encoded'] = True
                
                logger.info(f"Successfully processed request via {service['name']}")
                return response
            
            else:
                # Record failure and try next service
                service_manager.record_failure(service['name'])
                last_error = f"Service {service['name']} returned status {status_code}"
                logger.warning(last_error)
                continue
        
        # All services failed
        logger.error("All services failed to process the request")
        return {
            'statusCode': 503,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps({
                'error': 'Service not reachable at this moment',
                'message': 'All AI services failed to process the request. Please try again later.',
                'last_error': last_error,
                'timestamp': time.time()
            })
        }
        
    except Exception as e:
        logger.error(f"Lambda handler error: {str(e)}")
        return {
            'statusCode': 500,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps({
                'error': 'Internal server error',
                'message': str(e),
                'timestamp': time.time()
            })
        }

# For local testing
if __name__ == "__main__":
    # Test event
    test_event = {
        'httpMethod': 'GET',
        'path': '/health',
        'headers': {
            'Content-Type': 'application/json'
        },
        'queryStringParameters': None,
        'body': None
    }
    
    result = lambda_handler(test_event, None)
    print(json.dumps(result, indent=2)) 