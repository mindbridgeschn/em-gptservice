import os
import logging
import time
import requests
import redis
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from api.ocr import enqueue_task as enqueue_ocr_task, get_result as get_ocr_result
from api.ocr import ocr_worker_status, flush_ocr_redis
from api.miner_viewer import (
    enqueue_task_miner,
    get_result_miner,
    worker_status as miner_worker_status,
    get_miner_queue_items,
)


from api.em import enqueue_em_task, get_em_result
from services.cpt.cpt import cpt_coder
from services.cpt.cpt import get_cpt
from fastapi import Depends
from utils.health import get_health, get_liveness, get_readiness, get_startup
from utils.metrics import metrics_middleware, get_metrics
from fastapi.responses import Response
from utils.tracing import init_tracer, instrument_fastapi, get_tracer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)
class SuppressHealthAccessLogs(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        return not (
            "/health" in msg
            or "/health/liveness" in msg
            or "/health/readiness" in msg
            or "/health/startup" in msg
            or "/metrics" in msg
        )

logging.getLogger("uvicorn.access").addFilter(SuppressHealthAccessLogs())

logger = logging.getLogger("MainAPI")

load_dotenv()

# Initialize tracing early so it covers startup as well
# Service name will be read from OTEL_SERVICE_NAME env var, or defaults to "em-queue-api"
init_tracer(service_name=os.getenv("OTEL_SERVICE_NAME", "em-queue-api"))
tracer = get_tracer(__name__)

SEND_URL = os.getenv("SENDING_URL") or os.getenv("Sending_url")
REDIS_TTL = int(os.getenv("REDIS_TTL", "3600"))
GPU_LOAD_URL = os.getenv("GPU_LOAD")


def _make_redis_client() -> redis.Redis:
    try:
        raw_port = os.getenv("REDIS_PORT", "6379")
        if "://" in raw_port:
            raw_port = raw_port.split(":")[-1]

        client = redis.Redis(
            host=os.getenv("REDIS_HOST", "redis"),
            port=int(raw_port),
            password=os.getenv("REDIS_PASSWORD"),
            ssl=os.getenv("REDIS_SSL", "false").lower() == "true",
            decode_responses=True,
        )
        client.ping()
        logger.info("Redis connected successfully.")
        return client

    except Exception as ex:
        logger.critical(f"Fatal: Unable to connect to Redis → {ex}")
        raise SystemExit("Critical Redis Connection Failure")

redis_client = _make_redis_client()

app = FastAPI(title="E and M Rule engine")

# Attach OpenTelemetry FastAPI instrumentation
instrument_fastapi(app)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Add metrics middleware
@app.middleware("http")
async def add_metrics_middleware(request: Request, call_next):
    return await metrics_middleware(request, call_next)

# ==================== HEALTH & METRICS ====================
@app.get("/health")
async def health():
    """Overall health check endpoint"""
    return get_health()

@app.get("/health/liveness")
async def liveness():
    """Liveness probe - checks if application is running"""
    return get_liveness()

@app.get("/health/readiness")
async def readiness():
    """Readiness probe - checks if application is ready to serve traffic"""
    return get_readiness(fast=True)  # Use fast checks to avoid timeouts

@app.get("/health/startup")
async def startup():
    return get_startup()

@app.get("/metrics")
async def metrics():
    """Prometheus metrics endpoint"""
    return Response(content=get_metrics(), media_type="text/plain")

# ==================== API ENDPOINTS ====================

class TextRequest(BaseModel):
    text: str = Field(..., min_length=1)
    patientId: str

class PatientTask(BaseModel):
    patientId: str
    afterOcrBlobPath: str
    returnHeaders: dict = {}
    traceDto: dict = {}
    insurance: str = ""

class OcrTask(BaseModel):
    patientId: str
    sasToken: str
    blobSasToken: str
    afterOcrBlobPath: str
    returnHeaders: dict = {}
    traceDto: dict = {}
    connectionString: str

class MinerTask(BaseModel):
    patientId: str
    sasToken: str
    blobSasToken: str
    afterOcrBlobPath: str
    returnHeaders: dict = {}
    traceDto: dict = {}
    connectionString: str
    insurance: str

class Statusocr(BaseModel):
    patientId: str

class DemoRequest(BaseModel):
    blobUlr: str
    patientId: str
    traceDto: dict
    returnHeaders: dict

from pypdf import PdfReader
import io

def download_blob_text(url: str, patient_id: str = None) -> str:
    pid_log = f"patient={patient_id} " if patient_id else ""
    logger.info(f"[API-DOWNLOAD-START] {pid_log}url={url} Downloading blob")
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        reader = PdfReader(io.BytesIO(resp.content))
        text = "".join(page.extract_text() or "" for page in reader.pages)
        logger.info(f"[API-DOWNLOAD-SUCCESS] {pid_log}url={url} text_length={len(text)}")
        return text
    except requests.RequestException as e:
        logger.error(f"[API-DOWNLOAD-ERROR] {pid_log}url={url} Failed to download blob: {e}")
        raise HTTPException(status_code=503, detail=f"Failed to download blob: {str(e)}")
    except Exception as e:
        logger.error(f"[API-DOWNLOAD-ERROR] {pid_log}url={url} Failed to extract text from PDF: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to process PDF: {str(e)}")

@app.post("/add_patient_task")
async def add_patient_task_endpoint(task: PatientTask):
    try:
        logger.info(f"[API-EM-ENQUEUE-START] patient={task.patientId} endpoint=/add_patient_task blobPath={task.afterOcrBlobPath}")
        text = download_blob_text(task.afterOcrBlobPath, task.patientId)
        logger.info(f"[API-EM-ENQUEUE-TEXT] patient={task.patientId} text_length={len(text)}")

        enqueue_em_task({
            "patientId": task.patientId,
            "text": text,
            "traceDto": task.traceDto,
            "returnHeaders": task.returnHeaders,
            "insurance": task.insurance
        })

        logger.info(f"[API-EM-ENQUEUE-SUCCESS] patient={task.patientId} Task enqueued successfully")
        return {"status": "queued", "patientId": task.patientId}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[API-EM-ENQUEUE-ERROR] patient={task.patientId} Failed to enqueue task: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to enqueue task: {str(e)}")

from services.cpt.cpt import get_cpt
class CptRequest(BaseModel):
    text: str
    trace_id: str
    patientId: str
@app.post("/cpt")
async def cpt_endpoint(req: CptRequest):
    logger.info(f"[API-CPT-START] patient={req.patientId} endpoint=/cpt trace_id={req.trace_id} text_length={len(req.text)}")
    try:
        result = await get_cpt(req.text, req.trace_id, req.patientId)
        logger.info(f"[API-CPT-SUCCESS] patient={req.patientId} CPT processing completed")
        return result
    except Exception as e:
        logger.error(f"[API-CPT-ERROR] patient={req.patientId} CPT processing failed: {e}")
        raise

from api.em import em_worker_status, get_em_result, get_em_queue_items
from api.ocr import ocr_worker_status, get_ocr_queue_items

@app.get("/emWorkerStatus")
def em_worker_status_route():
    """Get EM worker status including queue details, errors and last success"""
    logger.info("[API-EM-STATUS] endpoint=/emWorkerStatus Fetching EM worker status")
    try:
        status = em_worker_status()
        logger.info(f"[API-EM-STATUS-SUCCESS] workerOnline={status.get('workerOnline')} queueLength={status.get('queueLength')} queueItems={status.get('queueItemsCount', 0)}")
        return {
            "status": "ok",
            "worker": status,
            "queue": {
                "name": "em_queue",
                "length": status.get("queueLength", 0),
                "items": status.get("queueItems", []),
                "itemsCount": status.get("queueItemsCount", 0)
            }
        }
    except Exception as e:
        logger.error(f"[API-EM-STATUS-ERROR] Failed to get worker status: {e}")
        return {
            "status": "error",
            "error": str(e),
            "worker": {"workerOnline": False},
            "queue": {"name": "em_queue", "length": 0, "items": []}
        }

@app.get("/emStatus/{patient_id}")
def em_status_route(patient_id: str):
    """Get EM processing status for a specific patient with full Redis details and error information"""
    logger.info(f"[API-EM-STATUS-PATIENT] patient={patient_id} endpoint=/emStatus/{patient_id} Fetching patient status")
    try:
        result = get_em_result(patient_id)
        logger.info(f"[API-EM-STATUS-PATIENT-SUCCESS] patient={patient_id} status={result.get('status', 'unknown')}")
        return result
    except Exception as e:
        logger.error(f"[API-EM-STATUS-PATIENT-ERROR] patient={patient_id} Failed to get status: {e}")
        return {
            "status": "error",
            "patientId": patient_id,
            "stage": "em",
            "error": str(e),
            "timestamp": time.time(),
            "redisStatus": {
                "connected": False,
                "error": "Failed to get Redis status"
            }
        }

@app.post("/OcrService")
def ocr_service(task: OcrTask):
    logger.info(f"[API-OCR-ENQUEUE-START] patient={task.patientId} endpoint=/OcrService blobPath={task.afterOcrBlobPath}")
    try:
        enqueue_ocr_task(task.dict())
        logger.info(f"[API-OCR-ENQUEUE-SUCCESS] patient={task.patientId} Task queued successfully")
        return {"status": "queued", "patientId": task.patientId}
    except Exception as e:
        logger.error(f"[API-OCR-ENQUEUE-ERROR] patient={task.patientId} Failed to enqueue task: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to enqueue OCR task: {str(e)}")

@app.post("/OcrStatus")
def ocr_status(task: Statusocr):
    """Get OCR processing status for a specific patient with full Redis details and error information"""
    logger.info(f"[API-OCR-STATUS] patient={task.patientId} endpoint=/OcrStatus Fetching OCR status")
    try:
        result = get_ocr_result(task.patientId)
        logger.info(f"[API-OCR-STATUS-SUCCESS] patient={task.patientId} status={result.get('status', 'unknown')}")
        return result
    except Exception as e:
        logger.error(f"[API-OCR-STATUS-ERROR] patient={task.patientId} Failed to get status: {e}")
        return {
            "status": "error",
            "patientId": task.patientId,
            "stage": "ocr",
            "error": str(e),
            "timestamp": time.time(),
            "redisStatus": {
                "connected": False,
                "error": "Failed to get Redis status"
            }
        }

@app.get("/ocrWorkerStatus")
def ocr_worker_status_route():
    """Get OCR worker status including queue details"""
    logger.info("[API-OCR-STATUS-WORKER] endpoint=/ocrWorkerStatus Fetching OCR worker status")
    try:
        status = ocr_worker_status()
        logger.info(f"[API-OCR-STATUS-WORKER-SUCCESS] workerOnline={status.get('workerOnline')} queueLength={status.get('queueLength')} queueItems={status.get('queueItemsCount', 0)}")
        return {
            "status": "ok",
            "worker": status,
            "queue": {
                "name": "ocr_queue",
                "length": status.get("queueLength", 0),
                "items": status.get("queueItems", []),
                "itemsCount": status.get("queueItemsCount", 0)
            }
        }
    except Exception as e:
        logger.error(f"[API-OCR-STATUS-WORKER-ERROR] Failed to get worker status: {e}")
        return {
            "status": "error",
            "error": str(e),
            "worker": {"workerOnline": False},
            "queue": {"name": "ocr_queue", "length": 0, "items": []}
        }

@app.get("/flushOcrRedis")
def flush_ocr_redis_route():
    logger.info("[API-OCR-FLUSH] endpoint=/flushOcrRedis Flushing OCR Redis")
    try:
        flush_ocr_redis()
        logger.info("[API-OCR-FLUSH-SUCCESS] OCR Redis flushed successfully")
        return {"status": "success", "message": "OCR Redis flushed"}
    except Exception as e:
        logger.error(f"[API-OCR-FLUSH-ERROR] Failed to flush OCR Redis: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to flush OCR Redis: {str(e)}")

@app.get("/allQueuesStatus")
def all_queues_status_route():
    """Get comprehensive status for all queues (EM, OCR, Miner) with full Redis details"""
    logger.info("[API-ALL-QUEUES-STATUS] endpoint=/allQueuesStatus Fetching all queues status")
    try:
        em_status = em_worker_status()
        ocr_status = ocr_worker_status()
        miner_status = miner_worker_status()
        
        total_queue_length = (
            em_status.get("queueLength", 0) + 
            ocr_status.get("queueLength", 0) + 
            miner_status.get("queueLength", 0)
        )
        
        result = {
            "status": "ok",
            "timestamp": time.time(),
            "totalQueueLength": total_queue_length,
            "queues": {
                "em": {
                    "name": "em_queue",
                    "workerOnline": em_status.get("workerOnline", False),
                    "redisConnected": em_status.get("redisConnected", False),
                    "redisStatus": em_status.get("redisStatus", {}),
                    "queueLength": em_status.get("queueLength", 0),
                    "queueItems": em_status.get("queueItems", []),
                    "queueItemsCount": em_status.get("queueItemsCount", 0),
                    "lastSuccess": em_status.get("lastSuccess"),
                    "lastError": em_status.get("lastError"),
                },
                "ocr": {
                    "name": "ocr_queue",
                    "workerOnline": ocr_status.get("workerOnline", False),
                    "redisConnected": ocr_status.get("redisConnected", False),
                    "redisStatus": ocr_status.get("redisStatus", {}),
                    "queueLength": ocr_status.get("queueLength", 0),
                    "queueItems": ocr_status.get("queueItems", []),
                    "queueItemsCount": ocr_status.get("queueItemsCount", 0),
                },
                "miner": {
                    "name": "miner_processing_queue",
                    "workerOnline": miner_status.get("workerOnline", False),
                    "redisConnected": miner_status.get("redisConnected", False),
                    "redisStatus": miner_status.get("redisStatus", {}),
                    "queueLength": miner_status.get("queueLength", 0),
                    "queueItems": miner_status.get("queueItems", []),
                    "queueItemsCount": miner_status.get("queueItemsCount", 0),
                    "ocrStatusUrl": miner_status.get("ocrStatusUrl"),
                }
            }
        }
        
        logger.info(f"[API-ALL-QUEUES-STATUS-SUCCESS] totalQueueLength={total_queue_length} em={em_status.get('queueLength', 0)} ocr={ocr_status.get('queueLength', 0)} miner={miner_status.get('queueLength', 0)}")
        return result
    except Exception as e:
        logger.error(f"[API-ALL-QUEUES-STATUS-ERROR] Failed to get all queues status: {e}")
        return {
            "status": "error",
            "error": str(e),
            "timestamp": time.time(),
            "totalQueueLength": 0,
            "queues": {
                "em": {"name": "em_queue", "error": str(e)},
                "ocr": {"name": "ocr_queue", "error": str(e)},
                "miner": {"name": "miner_processing_queue", "error": str(e)}
            }
        }


@app.post("/miner_process_task")
def process_task_endpoint(task: MinerTask):
    logger.info(f"[API-MINER-ENQUEUE-START] patient={task.patientId} endpoint=/miner_process_task blobPath={task.afterOcrBlobPath}")
    try:
        enqueue_task_miner(task.dict())
        logger.info(f"[API-MINER-ENQUEUE-SUCCESS] patient={task.patientId} Miner task queued successfully")
        return {"status": "Miner task queued"}
    except Exception as e:
        logger.error(f"[API-MINER-ENQUEUE-ERROR] patient={task.patientId} Failed to enqueue miner task: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/miner_task_result/{patient_id}")
def task_result(patient_id: str):
    """Get miner processing status for a specific patient with full Redis details and error information"""
    logger.info(f"[API-MINER-RESULT] patient={patient_id} endpoint=/miner_task_result/{patient_id} Fetching miner result")
    try:
        res = get_result_miner(patient_id)
        logger.info(f"[API-MINER-RESULT-SUCCESS] patient={patient_id} status={res.get('status', 'unknown') if res else 'pending'}")
        return res if res else {
            "status": "pending",
            "patientId": patient_id,
            "stage": "miner",
            "timestamp": time.time()
        }
    except Exception as e:
        logger.error(f"[API-MINER-RESULT-ERROR] patient={patient_id} Failed to get result: {e}")
        return {
            "status": "error",
            "patientId": patient_id,
            "stage": "miner",
            "error": str(e),
            "timestamp": time.time(),
            "redisStatus": {
                "connected": False,
                "error": "Failed to get Redis status"
            }
        }

@app.post("/enqueue_miner_task")
def enqueue_miner_task_endpoint(task: MinerTask):
    logger.info(f"[API-MINER-ENQUEUE-START] patient={task.patientId} endpoint=/enqueue_miner_task blobPath={task.afterOcrBlobPath}")
    try:
        enqueue_task_miner(task.dict())
        logger.info(f"[API-MINER-ENQUEUE-SUCCESS] patient={task.patientId} Miner task queued successfully")
        return {"status": "queued", "patientId": task.patientId}
    except Exception as e:
        logger.error(f"[API-MINER-ENQUEUE-ERROR] patient={task.patientId} Failed to enqueue miner task: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/miner_worker_status")
def worker_status_endpoint():
    """Get miner worker status including queue details and OCR status URL configuration"""
    logger.info("[API-MINER-STATUS-WORKER] endpoint=/miner_worker_status Fetching miner worker status")
    try:
        status = miner_worker_status()
        logger.info(f"[API-MINER-STATUS-WORKER-SUCCESS] workerOnline={status.get('workerOnline')} queueLength={status.get('queueLength')} queueItems={status.get('queueItemsCount', 0)}")
        return {
            "status": "ok",
            "worker": status,
            "queue": {
                "name": "miner_processing_queue",
                "length": status.get("queueLength", 0),
                "items": status.get("queueItems", []),
                "itemsCount": status.get("queueItemsCount", 0)
            }
        }
    except Exception as e:
        logger.error(f"[API-MINER-STATUS-WORKER-ERROR] Failed to get worker status: {e}")
        return {
            "status": "error",
            "error": str(e),
            "worker": {"workerOnline": False},
            "queue": {"name": "miner_processing_queue", "length": 0, "items": []}
        }

@app.get("/patientStatus/{patient_id}")
def patient_status_comprehensive(patient_id: str):
    """Get comprehensive patient status across all stages (OCR, Miner, EM) with full Redis details and errors"""
    logger.info(f"[API-PATIENT-STATUS] patient={patient_id} endpoint=/patientStatus/{patient_id} Fetching comprehensive patient status")
    try:
        # Get status from all stages
        ocr_result = get_ocr_result(patient_id)
        miner_result = get_result_miner(patient_id)
        em_result = get_em_result(patient_id)
        
        # Determine current stage and overall status
        stages = []
        current_stage = None
        overall_status = "unknown"
        errors = []
        
        # Check OCR stage
        ocr_status = ocr_result.get("status", "unknown")
        stages.append({
            "name": "ocr",
            "status": ocr_status,
            "details": ocr_result,
            "redisStatus": ocr_result.get("redisStatus", {}),
            "inQueue": ocr_result.get("inQueue", False),
            "queuePosition": ocr_result.get("queuePosition"),
            "resultKey": ocr_result.get("resultKey"),
            "timestamp": ocr_result.get("timestamp")
        })
        if ocr_status == "error":
            errors.append({"stage": "ocr", "error": ocr_result.get("error", "Unknown error")})
        if ocr_status == "processing":
            current_stage = "ocr"
            overall_status = "processing"
        
        # Check Miner stage
        miner_status = miner_result.get("status", "unknown") if miner_result else "not_started"
        stages.append({
            "name": "miner",
            "status": miner_status,
            "details": miner_result,
            "redisStatus": miner_result.get("redisStatus", {}) if miner_result else {},
            "inQueue": miner_result.get("inQueue", False) if miner_result else False,
            "queuePosition": miner_result.get("queuePosition") if miner_result else None,
            "resultKey": miner_result.get("resultKey") if miner_result else None,
            "timestamp": miner_result.get("timestamp") if miner_result else None
        })
        if miner_status == "error":
            errors.append({"stage": "miner", "error": miner_result.get("error", "Unknown error") if miner_result else "No result found"})
        if miner_status == "processing" and overall_status != "processing":
            current_stage = "miner"
            overall_status = "processing"
        if miner_status == "queued" and overall_status != "processing":
            current_stage = "miner"
            overall_status = "processing"
        
        # Check EM stage
        em_status = em_result.get("status", "unknown")
        stages.append({
            "name": "em",
            "status": em_status,
            "details": em_result,
            "redisStatus": em_result.get("redisStatus", {}),
            "inQueue": em_result.get("inQueue", False),
            "queuePosition": em_result.get("queuePosition"),
            "resultKey": em_result.get("resultKey"),
            "timestamp": em_result.get("timestamp")
        })
        if em_status == "error":
            errors.append({"stage": "em", "error": em_result.get("error", "Unknown error")})
        if em_status == "processing" and overall_status != "processing":
            current_stage = "em"
            overall_status = "processing"
        
        # Determine final status
        if ocr_status == "completed" and miner_status in ["completed", "queued", "not_started"] and em_status in ["completed", "processing", "queued"]:
            if em_status == "completed":
                overall_status = "completed"
                current_stage = "completed"
            else:
                overall_status = "processing"
                if not current_stage:
                    current_stage = "em"
        
        # Get Redis status from main client
        try:
            redis_info = redis_client.info()
            main_redis_status = {
                "connected": True,
                "host": os.getenv("REDIS_HOST", "redis"),
                "port": int(os.getenv("REDIS_PORT", "6379").split(":")[-1] if "://" in os.getenv("REDIS_PORT", "6379") else os.getenv("REDIS_PORT", "6379")),
                "ssl": os.getenv("REDIS_SSL", "false").lower() == "true",
                "server": {
                    "version": redis_info.get("redis_version", "unknown"),
                    "uptime_seconds": redis_info.get("uptime_in_seconds", 0),
                    "used_memory_human": redis_info.get("used_memory_human", "unknown"),
                    "connected_clients": redis_info.get("connected_clients", 0),
                    "total_commands_processed": redis_info.get("total_commands_processed", 0),
                },
                "stats": {
                    "keyspace_hits": redis_info.get("keyspace_hits", 0),
                    "keyspace_misses": redis_info.get("keyspace_misses", 0),
                    "keyspace_hit_rate": round(redis_info.get("keyspace_hits", 0) / max(redis_info.get("keyspace_hits", 0) + redis_info.get("keyspace_misses", 0), 1) * 100, 2) if (redis_info.get("keyspace_hits", 0) + redis_info.get("keyspace_misses", 0)) > 0 else 0,
                }
            }
        except Exception as e:
            main_redis_status = {
                "connected": False,
                "error": str(e)
            }
        
        result = {
            "patientId": patient_id,
            "overallStatus": overall_status,
            "currentStage": current_stage,
            "timestamp": time.time(),
            "redisStatus": main_redis_status,
            "stages": stages,
            "errors": errors if errors else None,
            "summary": {
                "ocr": {
                    "status": ocr_status,
                    "completed": ocr_status == "completed",
                    "processing": ocr_status == "processing",
                    "error": ocr_status == "error"
                },
                "miner": {
                    "status": miner_status,
                    "completed": miner_status == "completed" or miner_status == "queued",
                    "processing": miner_status == "processing",
                    "error": miner_status == "error"
                },
                "em": {
                    "status": em_status,
                    "completed": em_status == "completed",
                    "processing": em_status == "processing" or em_status == "queued",
                    "error": em_status == "error"
                }
            }
        }
        
        logger.info(f"[API-PATIENT-STATUS-SUCCESS] patient={patient_id} overallStatus={overall_status} currentStage={current_stage} errors={len(errors)}")
        return result
        
    except Exception as e:
        logger.error(f"[API-PATIENT-STATUS-ERROR] patient={patient_id} Failed to get comprehensive status: {e}")
        return {
            "patientId": patient_id,
            "overallStatus": "error",
            "error": str(e),
            "timestamp": time.time(),
            "redisStatus": {
                "connected": False,
                "error": "Failed to get Redis status"
            },
            "stages": [],
            "errors": [{"stage": "api", "error": str(e)}]
        }


@app.get("/loadGpu")
async def load_gpu_endpoint():
    try:
        resp = requests.get(GPU_LOAD_URL, timeout=10)
        return resp.json()
    except Exception:
        raise HTTPException(status_code=503, detail="GPU monitoring unavailable")


@app.get("/flushDbRedis")
async def flush_db_redis():
    try:
        redis_client.flushdb()
        return {"status": "success"}
    except Exception:
        logger.exception("Redis flush failed")
        raise HTTPException(status_code=500, detail="Redis flush failed")


from services.mdm.mdm import mdm_test

class test_mdmdddd(BaseModel):
    chart:str
@app.post("/testMdm")
async def medtest(chart_txt:test_mdmdddd):
    chart=chart_txt.chart
    return await mdm_test(chart)
#================================== CPT Engine ===========

class CPT_rule_prompt(BaseModel):
    chart:str
    prompt:str
    patientId:str

@app.post("/cpt_engine")
async def cpt_engine(payload:CPT_rule_prompt):
    text=payload.chart
    prompt=payload.prompt
    return await cpt_coder(text,prompt,payload.patientId)




# ==================== STARTUP ====================4
import ray

@app.on_event("startup")
async def startup_event():
    redis_client.flushdb()
    ray.init(ignore_reinit_error=True)

