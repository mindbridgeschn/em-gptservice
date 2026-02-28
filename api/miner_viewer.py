from fastapi import HTTPException
import redis
import requests
import json
import threading
import time
import os
import logging
from dotenv import load_dotenv
from utils.azureblob import generate_sas_from_connection_string

load_dotenv()

# ---------------------------
# Logging
# ---------------------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("miner-ocr-worker")

# ---------------------------
# Redis Client
# ---------------------------
def _make_redis_client() -> redis.Redis:
    raw_port = os.getenv("REDIS_PORT", "6379")
    if "://" in raw_port:
        raw_port = raw_port.split(":")[-1]

    redis_client = redis.Redis(host=os.getenv("REDIS_HOST"),port=int(raw_port),password=os.getenv("REDIS_PASSWORD"),ssl=os.getenv("REDIS_SSL", "false").lower() == "true", decode_responses=True )
    #redis_client = redis.Redis(host="localhost", port=6379, decode_responses=True)
    return redis_client


redis_client = _make_redis_client()
logger.info("[MINER-REDIS-CONNECT] Connected to Redis Miner")

# ---------------------------
# Constants
# ---------------------------
TASK_QUEUE = "miner_processing_queue"
RESULT_KEY_PREFIX = "miner_processing_result:"
RESULT_TTL = 86400  # 24 hours

OCR_ENGINE_URL = os.getenv("OCR_ENGINE_URL")
DEMO_URL = os.getenv("DEMO_URL")
ADD_TASK_URL = os.getenv("ADD_TASK_URL")
OCR_STATUS_URL = os.getenv("OCR_STATUS_URL")  # URL to send miner status updates

def post_request(url, data, headers=None, timeout=1420, retries=1, patient_id=None):
    patient_id = patient_id or data.get("patientId") if isinstance(data, dict) else None
    pid_log = f"patient={patient_id} " if patient_id else ""
    logger.info(f"[MINER-HTTP-REQUEST] {pid_log}url={url}")
    
    headers = headers or {"Content-Type": "application/json", "accept": "application/json"}
    attempt = 0
    while attempt <= retries:
        try:
            res = requests.post(url, json=data, headers=headers, timeout=timeout)
            res.raise_for_status()
            logger.info(f"[MINER-HTTP-SUCCESS] {pid_log}url={url} status={res.status_code}")
            return res.json()
        except Exception as e:
            attempt += 1
            if attempt > retries:
                logger.error(f"[MINER-HTTP-ERROR] {pid_log}url={url} attempt={attempt}/{retries} error={e}")
                return None
            logger.warning(f"[MINER-HTTP-RETRY] {pid_log}url={url} attempt={attempt}/{retries} retrying...")
            time.sleep(1)

def send_status_to_ocr_url(patient_id: str, status: dict, return_headers: dict = None):
    """Send miner status/result to OCR status URL"""
    if not OCR_STATUS_URL:
        logger.debug(f"[MINER-STATUS-SKIP] patient={patient_id} No OCR_STATUS_URL configured, skipping status callback")
        return
    
    try:
        status_payload = {
            "patientId": patient_id,
            "status": "completed",
            "result": status,
            "completedAt": time.time(),
            "source": "miner"
        }

        
        logger.info(f"[MINER-STATUS-START] patient={patient_id} Sending status to OCR URL")
        response = post_request(
            OCR_STATUS_URL,
            status_payload,
            headers=return_headers or {},
            timeout=30,
            retries=3,
            patient_id=patient_id
        )
        
        if response:
            logger.info(f"[MINER-STATUS-SUCCESS] patient={patient_id} Status sent successfully")
        else:
            logger.warning(f"[MINER-STATUS-FAILED] patient={patient_id} Failed to send status")
            
    except Exception as e:
        logger.error(f"[MINER-STATUS-ERROR] patient={patient_id} Failed to send status: {e}") 

# ---------------------------
# Task Processing
# ---------------------------
from api.em import enqueue_em_task
#from api.gliner_pii import pii_detection_demo
from pypdf import PdfReader
import io
def _download_blob_text(url: str, patient_id: str = None) -> str:
    pid_log = f"patient={patient_id} " if patient_id else ""
    logger.info(f"[MINER-DOWNLOAD-START] {pid_log}url={url}")
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        reader = PdfReader(io.BytesIO(resp.content))
        text = "".join(page.extract_text() or "" for page in reader.pages)
        logger.info(f"[MINER-DOWNLOAD-SUCCESS] {pid_log}url={url} text_length={len(text)}")
        return text
    except Exception as e:
        logger.error(f"[MINER-DOWNLOAD-ERROR] {pid_log}url={url} error={e}")
        raise

def process_request(task: dict):
    patient_id = task.get("patientId")
    if not patient_id:
        logger.error("[MINER-ERROR] Task missing patientId")
        return

    logger.info(f"[MINER-PROCESS-START] patient={patient_id}")
    logger.info(f"[MINER-TASK-PAYLOAD] patient={patient_id} payload={json.dumps(task, indent=2)}")
    logger.info(f"[MINER-OCR-REQUEST] patient={patient_id} url={OCR_ENGINE_URL}")

    ocr_rust_payload = {
        "patientId": patient_id,
        "insurance": task.get("insurance", ""),
        "sasToken": task["sasToken"],
        "blobSasToken": task["blobSasToken"],
        "afterOcrBlobPath": task["afterOcrBlobPath"],
        "returnHeaders": task.get("returnHeaders", {}),
        "connectionString": task.get("connectionString", ""),
        "traceDto": task.get("traceDto", {}),
    }

    ocr_response = post_request(OCR_ENGINE_URL, ocr_rust_payload, patient_id=patient_id)
    if not ocr_response:
        logger.error(f"[MINER-OCR-ERROR] patient={patient_id} OCR request failed")
        return

    logger.info(f"[MINER-OCR-SUCCESS] patient={patient_id} OCR completed")
    logger.info(f"[MINER-OCR-RESPONSE] patient={patient_id} response={json.dumps(ocr_response, indent=2)}")
    ocr_response= {
        "demoFile": ocr_response.get("demoFile", False),
        "isAFile": ocr_response.get("isAFile", False),
        "afterOcrBlobPath": ocr_response.get("afterOcrBlobPath", ""),
        "afterOcrSasUrl": ocr_response.get("afterOcrSasUrl", ""),
        "insurance": ocr_response.get("insurance", ""),
        "returnHeaders": ocr_response.get("returnHeaders", {}),
        "traceDto": ocr_response.get("traceDto", {}),
    }
    #is_file = ocr_response.get("isAFile", False)
    is_file = ocr_response.get("demoFile", False)
    logger.info(f"[MINER-FILE-CHECK] patient={patient_id} isAFile={is_file}")
    
    if is_file:
        logger.info(f"[MINER-DEMO-START] patient={patient_id} Processing as file (PII detection)")
        
        saas_token = generate_sas_from_connection_string(
            task.get("connectionString"), ocr_response.get("afterOcrBlobPath", "")
        )
        logger.info(f"[MINER-SAS-TOKEN] patient={patient_id} SAS token generated successfully")
        
        backend_payload = {
            "blobUlr": saas_token,
            "patientId": patient_id,
            "traceDto": ocr_response.get("traceDto", {}),
            "returnHeaders": ocr_response.get("returnHeaders", {}),
        }
        logger.info(f"[MINER-DEMO-PAYLOAD] patient={patient_id} payload={json.dumps(backend_payload, indent=2)}")
        
        #result = pii_detection_demo(
        #    backend_payload.get("blobUlr", ""), 
        #    patient_id, 
        #    backend_payload.get("traceDto", {}), 
         #   backend_payload.get("returnHeaders", {})
        #)
        #logger.info(f"[MINER-DEMO-SUCCESS] patient={patient_id} PII detection completed")
    else:
        logger.info(f"[MINER-EM-ENQUEUE-START] patient={patient_id} Processing as text (EM task enqueue)")

        backend_payload = {
            "patientId": patient_id,
            "afterOcrBlobPath": ocr_response.get("afterOcrBlobPath", ""),
            "returnHeaders": ocr_response.get("returnHeaders", {}),
            "traceDto": ocr_response.get("traceDto", {}),
            "insurance": ocr_response.get("insurance")
        }
        logger.info(f"[MINER-EM-PAYLOAD] patient={patient_id} payload={json.dumps(backend_payload, indent=2)}")
        
        #blob_path = backend_payload.get("afterOcrBlobPath", "")
        blob_path = ocr_response.get("afterOcrSasUrl", "")
        logger.info(f"[MINER-EM-BLOB-PATH] patient={patient_id} blobPath={blob_path}")
        
        text_content = _download_blob_text(blob_path, patient_id)
        logger.info(f"[MINER-EM-TEXT] patient={patient_id} text_length={len(text_content)} text_preview={text_content[:100]}")
        
        insurance = backend_payload.get("insurance", "")
        enqueue_input = {
            "text": f"insurance: {insurance}\n{text_content}",
            "patientId": patient_id,
            "afterOcrBlobPath": blob_path,
            "traceDto": backend_payload.get("traceDto", {}),
            "returnHeaders": backend_payload.get("returnHeaders", {}),
            "insurance": insurance
        }
        logger.info(f"[MINER-EM-ENQUEUE] patient={patient_id} insurance={insurance} text_length={len(enqueue_input['text'])}")
        
        enqueue_em_task(enqueue_input)
        logger.info(f"[MINER-EM-ENQUEUE-SUCCESS] patient={patient_id} EM task enqueued")
        
        # When EM task is enqueued, create a status indicating it's queued
        result = {
            "status": "queued",
            "patientId": patient_id,
            "message": "EM task enqueued for processing",
            "afterOcrBlobPath": blob_path,
            "traceDto": backend_payload.get("traceDto", {}),
            "insurance": insurance
        }
    
    redis_client.set(
        f"{RESULT_KEY_PREFIX}{patient_id}",
        json.dumps(result),
        ex=RESULT_TTL
    )

    logger.info(f"[MINER-STORE-SUCCESS] patient={patient_id} Result saved to Redis")

    # Send status to OCR URL
    return_headers = task.get("returnHeaders", {}) or ocr_response.get("returnHeaders", {})
    send_status_to_ocr_url(patient_id, result, return_headers)

    logger.info(f"[MINER-PROCESS-DONE] patient={patient_id} Processing completed")
    return result

# ---------------------------
# Worker Loop
# ---------------------------
def processing_worker_loop():
    logger.info("[MINER-WORKER-START] Worker started — Listening on miner_processing_queue")
    while True:
        try:
            item = redis_client.blpop(TASK_QUEUE, timeout=5)
            if not item:
                continue
            _, raw_task = item
            task = json.loads(raw_task)
            patient_id = task.get("patientId", "UNKNOWN")
            logger.info(f"[MINER-WORKER-TASK] patient={patient_id} Task received from queue")
            logger.debug(f"[MINER-WORKER-TASK-DEBUG] patient={patient_id} raw_task={raw_task}")
            
            process_request(task)
            logger.info(f"[MINER-WORKER-TASK-DONE] patient={patient_id} Task processing completed")

        except Exception as e:
            patient_id = "UNKNOWN"
            try:
                if 'task' in locals():
                    patient_id = task.get("patientId", "UNKNOWN")
            except:
                pass
            logger.error(f"[MINER-WORKER-ERROR] patient={patient_id} Worker loop error: {e}")
            time.sleep(3)

# ---------------------------
# FastAPI Helpers
# ---------------------------
def enqueue_task_miner(task: dict):
    patient_id = task.get('patientId', 'UNKNOWN')
    logger.info(f"[MINER-ENQUEUE] patient={patient_id} Task enqueued to miner queue")
    redis_client.rpush(TASK_QUEUE, json.dumps(task))
    logger.info(f"[MINER-ENQUEUE-SUCCESS] patient={patient_id} Task added to queue")

def get_result_miner(patient_id: str):
    """Get miner result for a patient with full details including Redis status"""
    try:
        res = redis_client.get(f"{RESULT_KEY_PREFIX}{patient_id}")
        redis_status = get_redis_status_details(redis_client)
        
        if not res:
            # Check if patient is in queue
            queue_items = get_miner_queue_items(limit=1000)
            in_queue = any(item.get("patientId") == patient_id for item in queue_items.get("items", []))
            
            return {
                "status": "processing",
                "patientId": patient_id,
                "stage": "miner",
                "inQueue": in_queue,
                "queuePosition": next((i for i, item in enumerate(queue_items.get("items", [])) if item.get("patientId") == patient_id), None),
                "redisStatus": redis_status,
                "resultKey": f"{RESULT_KEY_PREFIX}{patient_id}",
                "timestamp": time.time()
            }
        
        result = json.loads(res)
        result["redisStatus"] = redis_status
        result["resultKey"] = f"{RESULT_KEY_PREFIX}{patient_id}"
        return result
    except Exception as e:
        logger.error(f"[MINER-GET-RESULT-ERROR] patient={patient_id} error={e}")
        return {
            "status": "error",
            "patientId": patient_id,
            "stage": "miner",
            "error": str(e),
            "redisStatus": get_redis_status_details(redis_client) if redis_client else {"connected": False, "error": "Redis client not available"},
            "timestamp": time.time()
        }

def get_miner_queue_items(limit: int = 100):
    """Get items from Miner queue (without removing them)"""
    try:
        queue_length = redis_client.llen(TASK_QUEUE)
        items = []
        if queue_length > 0:
            # Use LRANGE to peek at items without removing them
            raw_items = redis_client.lrange(TASK_QUEUE, 0, limit - 1)
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
                        "insurance": task.get("insurance", ""),
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

def worker_status():
    try:
        queue_info = get_miner_queue_items(limit=50)
        redis_status = get_redis_status_details(redis_client)
        return {
            "workerOnline": True,
            "redisConnected": redis_client.ping(),
            "redisStatus": redis_status,
            "queueLength": queue_info.get("queueLength", 0),
            "queueItems": queue_info.get("items", []),
            "queueItemsCount": len(queue_info.get("items", [])),
            "ocrStatusUrl": OCR_STATUS_URL if OCR_STATUS_URL else None
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

def flush_miner_redis():
    logger.info("[MINER-FLUSH-START] Starting Redis flush")
    redis_client.delete(TASK_QUEUE)
    keys = redis_client.keys(f"{RESULT_KEY_PREFIX}*")
    if keys:
        redis_client.delete(*keys)
    logger.info(f"[MINER-FLUSH-SUCCESS] Redis cleaned queue={TASK_QUEUE} keys_deleted={len(keys)}")

# ---------------------------
# Auto-start worker thread
# ---------------------------
threading.Thread(target=processing_worker_loop, daemon=True).start()
logger.info("[MINER-WORKER-THREAD] MINER Worker Thread Started")
