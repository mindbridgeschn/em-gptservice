import time
from typing import Callable
from fastapi import Request, Response
from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST
from prometheus_client import REGISTRY
import logging

logger = logging.getLogger("metrics")

# HTTP Metrics
http_requests_total = Counter(
    "http_requests_total",
    "Total number of HTTP requests",
    ["method", "endpoint", "status_code"]
)

http_request_duration_seconds = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration in seconds",
    ["method", "endpoint"],
    buckets=[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0]
)

# Application Metrics
redis_operations_total = Counter(
    "redis_operations_total",
    "Total number of Redis operations",
    ["operation", "status"]
)

redis_operation_duration_seconds = Histogram(
    "redis_operation_duration_seconds",
    "Redis operation duration in seconds",
    ["operation"]
)

duckdb_operations_total = Counter(
    "duckdb_operations_total",
    "Total number of DuckDB operations",
    ["operation", "status"]
)

duckdb_operation_duration_seconds = Histogram(
    "duckdb_operation_duration_seconds",
    "DuckDB operation duration in seconds",
    ["operation"]
)

# Queue Metrics
queue_size = Gauge(
    "queue_size",
    "Current size of the queue",
    ["queue_name"]
)

queue_operations_total = Counter(
    "queue_operations_total",
    "Total number of queue operations",
    ["queue_name", "operation"]
)

# Worker Metrics
worker_status = Gauge(
    "worker_status",
    "Worker status (1 = online, 0 = offline)",
    ["worker_name"]
)

# System Metrics
system_memory_bytes = Gauge(
    "system_memory_bytes",
    "System memory usage in bytes",
    ["type"]
)

def normalize_path(path: str) -> str:
    """Normalize path for metrics (remove IDs, etc.)"""
    # Replace common ID patterns with placeholders
    import re
    # Replace UUIDs
    path = re.sub(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', '{id}', path, flags=re.IGNORECASE)
    # Replace numeric IDs
    path = re.sub(r'/\d+', '/{id}', path)
    return path

async def metrics_middleware(request: Request, call_next: Callable) -> Response:
    """Middleware to collect HTTP metrics"""
    start_time = time.time()
    
    # Skip metrics endpoint itself
    if request.url.path == "/metrics":
        return await call_next(request)
    
    method = request.method
    path = normalize_path(request.url.path)
    
    try:
        response = await call_next(request)
        status_code = response.status_code
        
        # Record metrics
        duration = time.time() - start_time
        http_requests_total.labels(method=method, endpoint=path, status_code=status_code).inc()
        http_request_duration_seconds.labels(method=method, endpoint=path).observe(duration)
        
        return response
    except Exception as e:
        status_code = 500
        duration = time.time() - start_time
        http_requests_total.labels(method=method, endpoint=path, status_code=status_code).inc()
        http_request_duration_seconds.labels(method=method, endpoint=path).observe(duration)
        logger.error(f"Request failed: {method} {path} - {str(e)}", exc_info=True)
        raise

def get_metrics():
    """Get Prometheus metrics"""
    return generate_latest(REGISTRY)

