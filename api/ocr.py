import redis
import requests
import logging
import threading
import time
import json
import os
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("ocr-worker")

# Redis settings
def _make_redis_client() -> redis.Redis:
    raw_port = os.getenv("REDIS_PORT", "6379")
    print(raw_port)
    print(os.getenv("REDIS_HOST", "redis"))
    if "://" in raw_port:
        raw_port = raw_port.split(":")[-1]
    redis_client = redis.Redis(host=os.getenv("REDIS_HOST", "redis"),port=int(raw_port),password=os.getenv("REDIS_PASSWORD"),ssl=os.getenv("REDIS_SSL", "false").lower() == "true", decode_responses=True )
    #redis_client = redis.Redis(host="localhost", port=6379, decode_responses=True)
    return redis_client

redis_client = _make_redis_client()
logger.info("[OCR-REDIS-CONNECT] Connected to Redis OCR")

OCR_URL = os.getenv("OCR_URL")
BACKEND_URL = os.getenv("OCR_BACKEND_URL")

QUEUE_NAME = "ocr_queue"
RESULT_PREFIX = "ocr_result:"

def post_with_retry(url, payload, headers=None, retries=3, timeout=120, patient_id=None):
    headers = headers or {}
    patient_id = patient_id or payload.get("patientId") if isinstance(payload, dict) else None
    pid_log = f"patient={patient_id} " if patient_id else ""
    
    for attempt in range(1, retries + 1):
        try:
            response = requests.post(url, json=payload, headers=headers, timeout=timeout)
            response.raise_for_status()
            logger.info(f"[OCR-HTTP-SUCCESS] {pid_log}url={url} status={response.status_code} attempt={attempt}/{retries}")
            return response
        except Exception as e:
            logger.error(f"[OCR-HTTP-ERROR] {pid_log}url={url} attempt={attempt}/{retries} error={e}")
            if attempt == retries:
                raise
            logger.warning(f"[OCR-HTTP-RETRY] {pid_log}url={url} attempt={attempt}/{retries} retrying...")
            time.sleep(3)

def enqueue_task(task: dict):
    patient_id = task.get('patientId', 'UNKNOWN')
    redis_client.rpush(QUEUE_NAME, json.dumps(task))
    logger.info(f"[OCR-ENQUEUE] patient={patient_id} Task enqueued to OCR queue")

def get_result(pid: str):
    """Get OCR result for a patient with full details including Redis status"""
    logger.info(f"[OCR-GET-RESULT] patient={pid} Fetching result from Redis")
    try:
        data = redis_client.get(f"{RESULT_PREFIX}{pid}")
        redis_status = get_redis_status_details(redis_client)
        
        if not data:
            # Check if patient is in queue
            queue_items = get_ocr_queue_items(limit=1000)
            in_queue = any(item.get("patientId") == pid for item in queue_items.get("items", []))
            
            logger.info(f"[OCR-GET-RESULT] patient={pid} Result not found, status=processing")
            return {
                "status": "processing",
                "patientId": pid,
                "stage": "ocr",
                "inQueue": in_queue,
                "queuePosition": next((i for i, item in enumerate(queue_items.get("items", [])) if item.get("patientId") == pid), None),
                "redisStatus": redis_status,
                "resultKey": f"{RESULT_PREFIX}{pid}",
                "timestamp": time.time()
            }
        
        logger.info(f"[OCR-GET-RESULT] patient={pid} Result found")
        result = json.loads(data)
        result["redisStatus"] = redis_status
        result["resultKey"] = f"{RESULT_PREFIX}{pid}"
        return result
    except Exception as e:
        logger.error(f"[OCR-GET-RESULT-ERROR] patient={pid} error={e}")
        return {
            "status": "error",
            "patientId": pid,
            "stage": "ocr",
            "error": str(e),
            "redisStatus": get_redis_status_details(redis_client) if redis_client else {"connected": False, "error": "Redis client not available"},
            "timestamp": time.time()
        }

def flush_ocr_redis():
    logger.info("[OCR-FLUSH-START] Starting OCR Redis flush")
    redis_client.delete(QUEUE_NAME)
    keys = list(redis_client.scan_iter(f"{RESULT_PREFIX}*"))
    for key in keys:
        redis_client.delete(key)
    logger.info(f"[OCR-FLUSH-SUCCESS] Redis cleaned queue={QUEUE_NAME} keys_deleted={len(keys)}")

def get_ocr_queue_items(limit: int = 100):
    """Get items from OCR queue (without removing them)"""
    try:
        queue_length = redis_client.llen(QUEUE_NAME)
        items = []
        if queue_length > 0:
            # Use LRANGE to peek at items without removing them
            raw_items = redis_client.lrange(QUEUE_NAME, 0, limit - 1)
            for raw_item in raw_items:
                try:
                    task = json.loads(raw_item)
                    items.append({
                        "patientId": task.get("patientId", "UNKNOWN"),
                        "hasSasToken": bool(task.get("sasToken")),
                        "hasBlobSasToken": bool(task.get("blobSasToken")),
                        "afterOcrBlobPath": task.get("afterOcrBlobPath", ""),
                        "hasTraceDto": bool(task.get("traceDto")),
                        "hasReturnHeaders": bool(task.get("returnHeaders")),
                    })
                except Exception as e:
                    items.append({"error": f"Failed to parse: {str(e)}"})
        return {
            "queueLength": queue_length,
            "items": items,
            "showing": len(items)
        }
    except Exception as e:
        return {"error": str(e), "queueLength": 0, "items": []}

def get_redis_status_details(redis_client_instance):
    """Get detailed Redis status information"""
    try:
        info = redis_client_instance.info()
        return {
            "connected": True,
            "host": os.getenv("REDIS_HOST", "redis"),
            "port": int(os.getenv("REDIS_PORT", "6379").split(":")[-1] if "://" in os.getenv("REDIS_PORT", "6379") else os.getenv("REDIS_PORT", "6379")),
            "ssl": os.getenv("REDIS_SSL", "false").lower() == "true",
            "server": {
                "version": info.get("redis_version", "unknown"),
                "uptime_seconds": info.get("uptime_in_seconds", 0),
                "used_memory_human": info.get("used_memory_human", "unknown"),
                "connected_clients": info.get("connected_clients", 0),
                "total_commands_processed": info.get("total_commands_processed", 0),
            },
            "stats": {
                "keyspace_hits": info.get("keyspace_hits", 0),
                "keyspace_misses": info.get("keyspace_misses", 0),
                "keyspace_hit_rate": round(info.get("keyspace_hits", 0) / max(info.get("keyspace_hits", 0) + info.get("keyspace_misses", 0), 1) * 100, 2) if (info.get("keyspace_hits", 0) + info.get("keyspace_misses", 0)) > 0 else 0,
            }
        }
    except Exception as e:
        return {
            "connected": False,
            "error": str(e),
            "host": os.getenv("REDIS_HOST", "redis"),
            "port": int(os.getenv("REDIS_PORT", "6379").split(":")[-1] if "://" in os.getenv("REDIS_PORT", "6379") else os.getenv("REDIS_PORT", "6379")),
        }

def ocr_worker_status():
    try:
        queue_info = get_ocr_queue_items(limit=50)
        redis_status = get_redis_status_details(redis_client)
        return {
            "workerOnline": True,
            "redisConnected": redis_client.ping(),
            "redisStatus": redis_status,
            "queueLength": queue_info.get("queueLength", 0),
            "queueItems": queue_info.get("items", []),
            "queueItemsCount": len(queue_info.get("items", [])),
        }
    except Exception as e:
        return {
            "workerOnline": False,
            "error": str(e),
            "redisConnected": False,
            "redisStatus": {"connected": False, "error": str(e)},
            "queueLength": 0,
            "queueItems": []
        }

def process_one_task(task: dict):
    pid = task["patientId"]
    logger.info(f"[OCR-PROCESS-START] patient={pid} Starting OCR processing")

    # OCR engine payload
    ocr_payload = {
        "patientId": pid,
        "sasToken": task["sasToken"],
        "blobSasToken": task["blobSasToken"],
        "afterOcrBlobPath": task["afterOcrBlobPath"],
        "returnHeaders": task.get("returnHeaders", {}),
        "connection_string": task.get("connectionString", ""),
        "traceDto": task.get("traceDto", {}),
    }

    logger.info(f"[OCR-ENGINE-REQUEST] patient={pid} url={OCR_URL} Sending to OCR engine payload={json.dumps(ocr_payload)}")
    # OCR call
    ocr_resp = post_with_retry(OCR_URL, ocr_payload, patient_id=pid)
    ocr_data = ocr_resp.json()
    logger.info(f"[OCR-ENGINE-SUCCESS] patient={pid} OCR engine completed")

    # Backend payload
    backend_payload = {
        "patientId": pid,
        "afterOcrBlobPath": ocr_data.get("afterOcrBlobPath"),
        "traceDto": ocr_data.get("traceDto", {}),
        "demoFile": ocr_data.get("demoFile"),
    }

    logger.info(f"[OCR-BACKEND-REQUEST] patient={pid} url={BACKEND_URL} Sending to backend")
    backend_resp = post_with_retry(
        BACKEND_URL,
        backend_payload,
        headers=ocr_data.get("returnHeaders", {}),
        patient_id=pid
    )
    backend_resp.raise_for_status()
    logger.info(f"[OCR-BACKEND-SUCCESS] patient={pid} Backend processing completed")

    final_data = {
        "status": "completed",
        "patientId": pid,
        "afterOcrBlobPath": backend_payload["afterOcrBlobPath"],
        "traceDto": backend_payload["traceDto"],
        "demoFile": backend_payload["demoFile"],
        "completedAt": time.time()
    }

    redis_client.set(f"{RESULT_PREFIX}{pid}", json.dumps(final_data))
    logger.info(f"[OCR-STORE-SUCCESS] patient={pid} Result saved to Redis key={RESULT_PREFIX}{pid}")
    logger.info(f"[OCR-PROCESS-DONE] patient={pid} OCR processing completed")

def worker_loop():
    logger.info("[OCR-WORKER-START] OCR Worker Online — STRICT FIFO MODE")
    while True:
        try:
            task_entry = redis_client.blpop(QUEUE_NAME, timeout=5)
            if not task_entry:
                continue

            _, raw = task_entry
            task = json.loads(raw)
            patient_id = task.get("patientId", "UNKNOWN")
            
            logger.info(f"[OCR-WORKER-TASK] patient={patient_id} Task received from queue")
            
            try:
                process_one_task(task)
                logger.info(f"[OCR-WORKER-TASK-DONE] patient={patient_id} Task processing completed")
            except Exception as e:
                logger.error(f"[OCR-WORKER-FAIL] patient={patient_id} Task processing failed: {e}")
                redis_client.rpush(QUEUE_NAME, json.dumps(task))  # fallback
                logger.warning(f"[OCR-WORKER-RETRY] patient={patient_id} Task re-queued for retry")
                time.sleep(3)
        except Exception as exc:
            logger.error(f"[OCR-WORKER-CRASH] patient=UNKNOWN Worker crash: {exc}")
            time.sleep(3)

# Startup auto-flush
if os.getenv("FLUSH_OCR_ON_STARTUP", "false").lower() == "true":
    flush_ocr_redis()

threading.Thread(target=worker_loop, daemon=True).start()
logger.info("[OCR-WORKER-THREAD] OCR Worker thread started")
