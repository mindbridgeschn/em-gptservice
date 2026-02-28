import os
import logging
import time
import redis
import duckdb
from typing import Dict, Any, Optional, Callable
from enum import Enum
import threading

logger = logging.getLogger("health")

class HealthStatus(str, Enum):
    UP = "UP"
    DOWN = "DOWN"

# Global reference to redis client (will be set from main.py)
_redis_client: Optional[redis.Redis] = None

# Track application startup status
_startup_complete = threading.Event()
_startup_failed = False
_startup_lock = threading.Lock()

def set_redis_client(client: redis.Redis):
    """Set the redis client to use for health checks"""
    global _redis_client
    _redis_client = client

def mark_startup_complete():
    """Mark application startup as complete"""
    global _startup_complete
    _startup_complete.set()

def mark_startup_failed():
    """Mark application startup as failed"""
    global _startup_failed
    with _startup_lock:
        _startup_failed = True

def is_startup_complete() -> bool:
    """Check if startup is complete"""
    return _startup_complete.is_set()

def check_redis(fast: bool = False) -> Dict[str, Any]:
    """Check Redis connection health - use existing client if available for speed"""
    try:
        # Use existing client if available (much faster)
        if _redis_client is not None:
            start_time = time.time()
            _redis_client.ping()
            response_time = (time.time() - start_time) * 1000
            return {
                "status": HealthStatus.UP,
                "details": {
                    "responseTime": f"{response_time:.2f}ms"
                }
            }
        
        # Fallback: create new connection (slower)
        raw_port = os.getenv("REDIS_PORT", "6379")
        if "://" in raw_port:
            raw_port = raw_port.split(":")[-1]

        timeout = 1 if fast else 2
        client = redis.Redis(
            host=os.getenv("REDIS_HOST", "redis"),
            port=int(raw_port),
            password=os.getenv("REDIS_PASSWORD"),
            ssl=os.getenv("REDIS_SSL", "false").lower() == "true",
            decode_responses=True,
            socket_connect_timeout=timeout,
            socket_timeout=timeout,
        )
        try:
            start_time = time.time()
            client.ping()
            response_time = (time.time() - start_time) * 1000
        finally:
            client.close()
        
        return {
            "status": HealthStatus.UP,
            "details": {
                "responseTime": f"{response_time:.2f}ms"
            }
        }
    except Exception as e:
        if not fast:  # Only log errors for non-fast checks
            logger.error(f"Redis health check failed: {e}")
        return {
            "status": HealthStatus.DOWN,
            "details": {
                "error": str(e)
            }
        }

def check_duckdb(fast: bool = False) -> Dict[str, Any]:
    """Check DuckDB connection health - optimized for speed"""
    try:
        db_path = "data/rag_logs.duckdb"
        start_time = time.time()
        conn = duckdb.connect(db_path, read_only=True)  # Read-only is faster
        conn.execute("SELECT 1")
        response_time = (time.time() - start_time) * 1000
        conn.close()
        
        return {
            "status": HealthStatus.UP,
            "details": {
                "responseTime": f"{response_time:.2f}ms"
            }
        }
    except Exception as e:
        if not fast:  # Only log errors for non-fast checks
            logger.error(f"DuckDB health check failed: {e}")
        return {
            "status": HealthStatus.DOWN,
            "details": {
                "error": str(e)
            }
        }

def check_disk_space() -> Dict[str, Any]:
    """Check disk space availability"""
    try:
        import shutil
        import os
        # Check disk space for the current working directory
        # If directory doesn't exist, check parent or root
        check_path = "."
        if not os.path.exists(check_path):
            check_path = os.path.dirname(os.path.abspath(check_path)) or "/"
        
        total, used, free = shutil.disk_usage(check_path)
        free_gb = free / (1024 ** 3)
        total_gb = total / (1024 ** 3)
        free_percent = (free / total) * 100 if total > 0 else 0
        
        status = HealthStatus.UP if free_percent > 10 else HealthStatus.DOWN
        
        return {
            "status": status,
            "details": {
                "free": f"{free_gb:.2f}GB",
                "total": f"{total_gb:.2f}GB",
                "freePercent": f"{free_percent:.2f}%"
            }
        }
    except Exception as e:
        logger.error(f"Disk space check failed: {e}")
        return {
            "status": HealthStatus.DOWN,
            "details": {
                "error": str(e)
            }
        }

def get_health() -> Dict[str, Any]:
    """Get overall health status"""
    checks = {
        "redis": check_redis(),
        "duckdb": check_duckdb(),
        "disk": check_disk_space(),
    }
    
    overall_status = HealthStatus.UP
    if any(check["status"] == HealthStatus.DOWN for check in checks.values()):
        overall_status = HealthStatus.DOWN
    
    return {
        "status": overall_status.value,
        "components": checks
    }

def get_liveness() -> Dict[str, Any]:
    """Liveness probe - checks if the application is running (fast, no dependencies)"""
    # Liveness should be super fast - just check if app is alive
    return {
        "status": HealthStatus.UP.value
    }

def get_readiness(fast: bool = False) -> Dict[str, Any]:
    """Readiness probe - checks if the application is ready to serve traffic"""
    # Don't mark as ready until startup is complete
    if not is_startup_complete():
        return {
            "status": HealthStatus.DOWN.value,
            "components": {
                "startup": "in_progress",
                "note": "Application is still starting up"
            }
        }
    
    # Use fast checks for readiness to avoid timeouts
    redis_check = check_redis(fast=fast)
    duckdb_check = check_duckdb(fast=fast)
    
    # Application is ready if critical dependencies are up
    if redis_check["status"] == HealthStatus.UP and duckdb_check["status"] == HealthStatus.UP:
        return {
            "status": HealthStatus.UP.value,
            "components": {
                "redis": redis_check,
                "duckdb": duckdb_check
            }
        }
    else:
        return {
            "status": HealthStatus.DOWN.value,
            "components": {
                "redis": redis_check,
                "duckdb": duckdb_check
            }
        }

def get_startup() -> Dict[str, Any]:
    """Startup probe - checks if the application has finished starting up"""
    # Startup probe should always return UP if the server is responding
    # It's just checking if the HTTP server is up, not if models are loaded
    with _startup_lock:
        startup_failed = _startup_failed
    
    if startup_failed:
        return {
            "status": HealthStatus.DOWN.value,
            "components": {
                "error": "Startup failed"
            }
        }
    
    # If startup is complete, return UP
    if is_startup_complete():
        return {
            "status": HealthStatus.UP.value,
            "components": {
                "startup": "complete"
            }
        }
    
    # During startup, still return UP (server is responding)
    return {
        "status": HealthStatus.UP.value,
        "components": {
            "startup": "in_progress"
        }
    }

