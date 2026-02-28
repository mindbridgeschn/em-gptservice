import os
import json
import logging
import time
import redis
import requests
import asyncio
import ray
from dotenv import load_dotenv

from services.cpt.cpt import get_cpt
from services.hcpcs.hcpcs import get_hcpcs
from services.icd.icd import get_icd
from services.mdm.mdm import get_mdm
from api.gliner_pii import pii_ai_demo
from opentelemetry import trace
from utils.tracing import init_tracer, get_tracer, use_trace_dto_context, add_trace_dto_to_span

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("em-worker")

# Initialize tracing once per worker process
# Service name will be read from OTEL_SERVICE_NAME env var, or defaults to "em-worker"
init_tracer(service_name=os.getenv("OTEL_SERVICE_NAME", "em-worker"))
tracer = get_tracer(__name__)

def _make_redis_client() -> redis.Redis:
    raw_port = os.getenv("REDIS_PORT", "6379")
    if "://" in raw_port:
        raw_port = raw_port.split(":")[-1]

    return redis.Redis(
        host=os.getenv("REDIS_HOST", "redis"),
        port=int(raw_port),
        password=os.getenv("REDIS_PASSWORD"),
        ssl=os.getenv("REDIS_SSL", "false").lower() == "true",
        decode_responses=True,
    )

redis_client = _make_redis_client()

EM_QUEUE = "em_queue"
EM_RESULT_PREFIX = "em_result:"
EM_LAST_SUCCESS = "EM_LAST_SUCCESS"
EM_LAST_ERROR = "EM_LAST_ERROR"

SEND_URL = os.getenv("SEND")
MAX_RETRIES = 3

@ray.remote
def mdm_remote(text, trace):   return asyncio.run(get_mdm(text, trace))

@ray.remote
def icd_remote(text, trace):   return asyncio.run(get_icd(text, trace))

@ray.remote
def demo_remote(text,patientId): return asyncio.run(pii_ai_demo(text, patientId))

#@ray.remote
#def cpt_remote(text, trace, patientId):   return asyncio.run(get_cpt(text, trace, patientId))

#@ray.remote
#def hcpcs_remote(text, trace): return asyncio.run(get_hcpcs(text, trace))


def enqueue_em_task(task: dict):
    patient_id = task.get('patientId', 'UNKNOWN')
    redis_client.rpush(EM_QUEUE, json.dumps(task))
    logger.info(f"[EM-ENQUEUE] patient={patient_id} Task enqueued to EM queue")


def get_em_queue_items(limit: int = 100):
    """Get items from EM queue (without removing them)"""
    try:
        queue_length = redis_client.llen(EM_QUEUE)
        items = []
        if queue_length > 0:
            # Use LRANGE to peek at items without removing them
            raw_items = redis_client.lrange(EM_QUEUE, 0, limit - 1)
            for raw_item in raw_items:
                try:
                    task = json.loads(raw_item)
                    items.append({
                        "patientId": task.get("patientId", "UNKNOWN"),
                        "hasText": bool(task.get("text")),
                        "textLength": len(task.get("text", "")),
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

def em_worker_status():
    try:
        last_success = redis_client.get(EM_LAST_SUCCESS)
        last_error = redis_client.get(EM_LAST_ERROR)
        queue_info = get_em_queue_items(limit=50)
        redis_status = get_redis_status_details(redis_client)

        return {
            "workerOnline": True,
            "redisConnected": redis_client.ping(),
            "redisStatus": redis_status,
            "queueLength": queue_info.get("queueLength", 0),
            "queueItems": queue_info.get("items", []),
            "queueItemsCount": len(queue_info.get("items", [])),
            "lastSuccess": json.loads(last_success) if last_success else None,
            "lastError": json.loads(last_error) if last_error else None,
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


def get_em_result(pid: str):
    try:
        data = redis_client.get(f"{EM_RESULT_PREFIX}{pid}")
        redis_status = get_redis_status_details(redis_client)
        
        if not data:
            # Check if patient is in queue
            queue_items = get_em_queue_items(limit=1000)
            in_queue = any(item.get("patientId") == pid for item in queue_items.get("items", []))
            
            return {
                "status": "processing",
                "patientId": pid,
                "stage": "em",
                "inQueue": in_queue,
                "queuePosition": next((i for i, item in enumerate(queue_items.get("items", [])) if item.get("patientId") == pid), None),
                "redisStatus": redis_status,
                "resultKey": f"{EM_RESULT_PREFIX}{pid}",
                "timestamp": time.time()
            }
        
        result = json.loads(data)
        result["redisStatus"] = redis_status
        result["resultKey"] = f"{EM_RESULT_PREFIX}{pid}"
        return result
    except Exception as e:
        logger.error(f"[EM-GET-RESULT-ERROR] patient={pid} error={e}")
        return {
            "status": "error",
            "patientId": pid,
            "stage": "em",
            "error": str(e),
            "redisStatus": get_redis_status_details(redis_client) if redis_client else {"connected": False, "error": "Redis client not available"},
            "timestamp": time.time()
        }


def post_with_retry(url, payload, headers=None, retries=3, patient_id=None):
    headers = headers or {}
    patient_id = patient_id or payload.get("patientId") if isinstance(payload, dict) else None
    pid_log = f"patient={patient_id} " if patient_id else ""

    for attempt in range(1, retries + 1):
        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=30)
            resp.raise_for_status()
            logger.info(f"[EM-HTTP-SUCCESS] {pid_log}url={url} status={resp.status_code} attempt={attempt}/{retries}")
            return resp
        except Exception as e:
            logger.error(f"[EM-HTTP-ERROR] {pid_log}url={url} attempt={attempt}/{retries} error={e}")
            if attempt == retries:
                raise
            logger.warning(f"[EM-HTTP-RETRY] {pid_log}url={url} attempt={attempt}/{retries} retrying...")
            time.sleep(2)


async def process_one_em_async(task: dict):
    pid = task["patientId"]
    text = task["text"]
    trace_dto = task.get("traceDto", {})
    trace_id = trace_dto.get("traceId", "") if trace_dto else ""

    logger.info(f"[EM-PROCESS-START] patient={pid} Starting medical extraction {task}")
    logger.info(f"[EM-PROCESS-TEXT] patient={pid} text_length={len(text)} text_preview={text[:100]}")
    logger.info(f"[EM-PROCESS-RAY] patient={pid} trace={trace_id} Starting Ray remote tasks")
    
    # Add traceDto info to current span if available
    current_span = trace.get_current_span()
    if current_span and trace_dto:
        add_trace_dto_to_span(current_span, trace_dto)
    
    #mdm_f, icd_f, cpt_f, hcpcs_f = await asyncio.gather(
    #    mdm_remote.remote(text, trace_id),
    #    icd_remote.remote(text, trace_id),
    #    cpt_remote.remote(text, trace_id, pid),
    #    hcpcs_remote.remote(text, trace_id),
    #)
    mdm_f, icd_f,demo_f = await asyncio.gather(
        mdm_remote.remote(text, trace_id),
        icd_remote.remote(text, trace_id),
        demo_remote.remote(text,pid)

    )

    logger.info(f"[EM-PROCESS-RAY-DONE] patient={pid} All Ray tasks completed")

    final_payload = {
        "patientId": pid,
        "demoResponse":demo_f,
        "procedureMapping": {
            "source_data": {
                "icd_data": icd_f,
                "cpt_data": {
                    "all_cpt_list": [],
                    "hcpec_list": {},
                }
            },
            "mapping": {
                "icd_to_cpt_mapping": {},
                "icd_to_hcpcs_mapping": {}
            }
        },
        "medicalEvaluation": mdm_f,
        "traceDto": task.get("traceDto", {}),
    }
    logger.info(f"[EM-PROCESS-DONE] patient={pid} Medical extraction completed")
    logger.info(f"[EM-PROCESS-RESULT] patient={pid} result={json.dumps(final_payload, indent=2)}")
    return final_payload


def process_one_em(task: dict):
    pid = task["patientId"]
    header=task["returnHeaders"]
    trace_dto = task.get("traceDto", {})
    
    try:
        # Use traceDto context if available, otherwise create new trace
        with use_trace_dto_context(trace_dto, "em.process_one_em") as span:
            # Add patient ID and other task info to span
            span.set_attribute("patient.id", pid)
            span.set_attribute("task.type", "em_processing")
            result = asyncio.run(process_one_em_async(task))
    except Exception as e:
        logger.error(f"[EM-PROCESS-ERROR] patient={pid} Failed during processing: {e}")

        redis_client.set(EM_LAST_ERROR, json.dumps({
            "patientId": pid,
            "timestamp": time.time(),
            "error": str(e)
        }))

        raise

    try:
        logger.info(f"[EM-SEND-START] patient={pid} url={SEND_URL} Sending result to backend")
        logger.info(f"[EM-Debug] patient={pid} result {result} header {header}")
        resp = post_with_retry(
            SEND_URL,
            result,
            headers=header,
            retries=MAX_RETRIES,
            patient_id=pid
        )
        logger.info(f"[EM-SEND-SUCCESS] patient={pid} status={resp.status_code} Result sent successfully")

    except Exception as e:
        logger.error(f"[EM-SEND-ERROR] patient={pid} url={SEND_URL} Failed to send result: {e}")
        raise

    # Persist final result
    redis_client.set(f"{EM_RESULT_PREFIX}{pid}", json.dumps({
        "status": "completed",
        "patientId": pid,
        "result": result,
        "completedAt": time.time(),
    }))

    # Track last success
    redis_client.set(EM_LAST_SUCCESS, json.dumps({
        "patientId": pid,
        "timestamp": time.time(),
        "resultKey": f"{EM_RESULT_PREFIX}{pid}"
    }))

    logger.info(f"[EM-STORE-SUCCESS] patient={pid} Result saved to Redis key={EM_RESULT_PREFIX}{pid}")


def em_worker_loop():
    logger.info("[EM-WORKER-START] EM Worker Online — STRICT FIFO MODE")

    while True:
        try:
            entry = redis_client.blpop(EM_QUEUE, timeout=5)
            if not entry:
                continue

            _, raw = entry
            task = json.loads(raw)
            patient_id = task.get("patientId", "UNKNOWN")
            logger.info(f"[EM-WORKER-TASK] patient={patient_id} Task received from queue")

            try:
                process_one_em(task)
                logger.info(f"[EM-WORKER-TASK-DONE] patient={patient_id} Task processing completed")

            except Exception as err:
                logger.error(f"[EM-WORKER-FAIL] patient={patient_id} Task processing failed: {err}")

                redis_client.set(EM_LAST_ERROR, json.dumps({
                    "patientId": patient_id,
                    "timestamp": time.time(),
                    "error": str(err)
                }))

                redis_client.rpush(EM_QUEUE, json.dumps(task))
                logger.warning(f"[EM-WORKER-RETRY] patient={patient_id} Task re-queued for retry")
                time.sleep(2)

        except Exception as crash:
            logger.error(f"[EM-WORKER-CRASH] patient=UNKNOWN Worker crash: {crash}")

            redis_client.set(EM_LAST_ERROR, json.dumps({
                "patientId": "N/A",
                "timestamp": time.time(),
                "error": str(crash)
            }))

            time.sleep(2)


AUTO_FLUSH = os.getenv("FLUSH_EM_ON_STARTUP", "false").lower() == "true"
if AUTO_FLUSH:
    redis_client.delete(EM_QUEUE)
    keys = list(redis_client.scan_iter(f"{EM_RESULT_PREFIX}*"))
    for key in keys:
        redis_client.delete(key)
    logger.warning(f"[EM-FLUSH] EM Redis queue flushed on startup queue={EM_QUEUE} keys_deleted={len(keys)}")

import threading
threading.Thread(target=em_worker_loop, daemon=True).start()
logger.info("[EM-WORKER-THREAD] EM Worker thread started")
