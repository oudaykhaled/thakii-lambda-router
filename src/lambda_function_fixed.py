import json
import requests
import time
import random
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
            if service_name in self.circuit_breakers:
                circuit_data = self.circuit_breakers[service_name]
                if circuit_data['status'] == 'open':
                    # Check if recovery timeout has passed
                    recovery_timeout = self.config.get('circuit_breaker', {}).get('recovery_timeout', 60)
                    if current_time - circuit_data['last_failure'] < recovery_timeout:
                        logger.info(f"Circuit breaker open for {service_name}, skipping")
                        continue
                    else:
                        # Reset circuit breaker for retry
                        logger.info(f"Circuit breaker recovery timeout passed for {service_name}, resetting")
                        self.circuit_breakers[service_name] = {
                            'status': 'half-open',
                            'failures': 0,
                            'last_failure': 0
                        }
            
            available.append(service)
        
        # Sort by priority (lower number = higher priority)
        return sorted(available, key=lambda s: s.get('priority', 999))
    
    def record_success(self, service_name: str):
        """Record a successful request to a service"""
        if service_name in self.circuit_breakers and self.circuit_breakers[service_name]['status'] == 'half-open':
            # Reset circuit breaker on successful request in half-open state
            logger.info(f"Service {service_name} recovered, closing circuit breaker")
            self.circuit_breakers[service_name] = {
                'status': 'closed',
                'failures': 0,
                'last_failure': 0
            }
    
    def record_failure(self, service_name: str):
        """Record a failed request to a service"""
        current_time = time.time()
        
        if service_name not in self.circuit_breakers:
            self.circuit_breakers[service_name] = {
                'status': 'closed',
                'failures': 0,
                'last_failure': 0
            }
        
        circuit_data = self.circuit_breakers[service_name]
        circuit_data['failures'] += 1
        circuit_data['last_failure'] = current_time
        
        # Check if we need to open the circuit breaker
        failure_threshold = self.config.get('circuit_breaker', {}).get('failure_threshold', 5)
        if circuit_data['failures'] >= failure_threshold:
            logger.warning(f"Circuit breaker tripped for {service_name} after {circuit_data['failures']} failures")
            circuit_data['status'] = 'open'
        
        self.circuit_breakers[service_name] = circuit_data
    
    def forward_request(self, path: str, method: str, headers: Dict, body: Optional[str] = None, 
                       query_params: Optional[Dict] = None) -> Tuple[int, Dict, str]:
        """Forward the request to an available service"""
        available_services = self.get_available_services()
        
        if not available_services:
            logger.error("No available services found")
            return 503, {}, json.dumps({
                "error": "Service not reachable at this moment",
                "message": "All AI services are currently unavailable. Please try again later.",
                "timestamp": time.time()
            })
        
        # Determine which load balancing strategy to use
        load_balancing = self.config.get('load_balancing', {})
        strategy = load_balancing.get('strategy', 'priority')
        
        if strategy == 'round_robin' and load_balancing.get('round_robin_enabled', False):
            # Simple round-robin: take the first service and move it to the end for next request
            service = available_services[0]
            # We don't actually modify the list here as it's recreated each time from config
        else:
            # Default: priority-based (already sorted by priority)
            service = available_services[0]
        
        service_name = service['name']
        service_url = service['url']
        
        # Log the request details
        logger.info(f"Forwarding request to {service_name} at {service_url}{path}")
        logger.info(f"Method: {method}, Path: {path}")
        if query_params:
            logger.info(f"Query params: {query_params}")
        
        # Construct the full URL
        url = f"{service_url}{path}"
        
        # Set timeout from service config or default
        timeout = service.get('timeout', self.config.get('default_timeout', 30))
        
        try:
            if method.upper() == 'GET':
                response = requests.get(url, headers=headers, params=query_params, timeout=timeout)
            elif method.upper() == 'POST':
                response = requests.post(url, headers=headers, data=body, params=query_params, timeout=timeout)
            elif method.upper() == 'PUT':
                response = requests.put(url, headers=headers, data=body, params=query_params, timeout=timeout)
            elif method.upper() == 'DELETE':
                response = requests.delete(url, headers=headers, params=query_params, timeout=timeout)
            else:
                logger.error(f"Unsupported HTTP method: {method}")
                return 400, {}, json.dumps({
                    "error": "Bad request",
                    "message": f"Unsupported HTTP method: {method}"
                })
            
            # Log the response status
            logger.info(f"Service {service_name} returned status {response.status_code}")
            
            # Check if the request was successful
            if 200 <= response.status_code < 300:
                self.record_success(service_name)
                return response.status_code, dict(response.headers), response.text
            else:
                self.record_failure(service_name)
                
                # Try the next service if available
                if len(available_services) > 1:
                    logger.info(f"Trying next available service after failure from {service_name}")
                    # Remove the failed service and try again
                    remaining_services = [s for s in available_services if s['name'] != service_name]
                    if remaining_services:
                        next_service = remaining_services[0]
                        next_service_name = next_service['name']
                        next_service_url = next_service['url']
                        
                        url = f"{next_service_url}{path}"
                        timeout = next_service.get('timeout', self.config.get('default_timeout', 30))
                        
                        try:
                            if method.upper() == 'GET':
                                response = requests.get(url, headers=headers, params=query_params, timeout=timeout)
                            elif method.upper() == 'POST':
                                response = requests.post(url, headers=headers, data=body, params=query_params, timeout=timeout)
                            elif method.upper() == 'PUT':
                                response = requests.put(url, headers=headers, data=body, params=query_params, timeout=timeout)
                            elif method.upper() == 'DELETE':
                                response = requests.delete(url, headers=headers, params=query_params, timeout=timeout)
                            
                            logger.info(f"Fallback service {next_service_name} returned status {response.status_code}")
                            
                            if 200 <= response.status_code < 300:
                                self.record_success(next_service_name)
                                return response.status_code, dict(response.headers), response.text
                            else:
                                self.record_failure(next_service_name)
                        except Exception as e:
                            logger.error(f"Error from fallback service {next_service_name}: {str(e)}")
                            self.record_failure(next_service_name)
                
                # If we get here, all attempts failed
                return 503, {}, json.dumps({
                    "error": "Service not reachable at this moment",
                    "message": "All AI services failed to process the request. Please try again later.",
                    "last_error": f"Service {service_name} returned status {response.status_code}",
                    "timestamp": time.time()
                })
                
        except Exception as e:
            logger.error(f"Error forwarding request to {service_name}: {str(e)}")
            self.record_failure(service_name)
            
            return 503, {}, json.dumps({
                "error": "Service not reachable at this moment",
                "message": "All AI services failed to process the request. Please try again later.",
                "last_error": f"Service {service_name} error: {str(e)}",
                "timestamp": time.time()
            })

def lambda_handler(event, context):
    # Load configuration
    try:
        with open('config.json', 'r') as f:
            config = json.load(f)
        
        logger.info("Loaded configuration successfully")
        logger.info(f"Event: {json.dumps(event)}")
        
        service_manager = ServiceManager(config)
        
        # Extract request details from API Gateway event
        method = event.get('httpMethod', 'GET')
        path = event.get('path', '')
        headers = event.get('headers', {})
        query_params = event.get('queryStringParameters', {})
        
        # Handle binary data for POST requests
        body = None
        if method == 'POST' and 'body' in event:
            if event.get('isBase64Encoded', False):
                import base64
                body = base64.b64decode(event['body'])
            else:
                body = event['body']
        
        # Log the request details
        logger.info(f"Received {method} request for {path}")
        
        # Forward the request to an available service
        status_code, response_headers, response_body = service_manager.forward_request(
            path, method, headers, body, query_params
        )
        
        # Handle binary responses if needed
        is_base64_encoded = False
        content_type = response_headers.get('Content-Type', '')
        if content_type and ('image/' in content_type or 'application/octet-stream' in content_type):
            import base64
            response_body = base64.b64encode(response_body.encode('utf-8')).decode('utf-8')
            is_base64_encoded = True
        
        return {
            'statusCode': status_code,
            'headers': response_headers,
            'body': response_body,
            'isBase64Encoded': is_base64_encoded
        }
        
    except Exception as e:
        logger.error(f"Error in lambda_handler: {str(e)}")
        return {
            'statusCode': 500,
            'body': json.dumps({
                'message': 'Internal server error',
                'error': str(e)
            })
        }
