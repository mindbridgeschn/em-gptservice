import json
import logging
from utils.ai import ai_call
from services.cpt.cpt_prompt import prompt

logger = logging.getLogger(__name__)

def json_clean(value):
    if isinstance(value, (list, dict)):
        return value

    if isinstance(value, str):
        cleaned = value.strip()
        if cleaned.startswith("```json"):
            cleaned = cleaned.replace("```json", "").replace("```", "").strip()
        try:
            return json.loads(cleaned)
        except Exception:
            logger.warning("[CPT] Failed to parse AI response as JSON")
            return []

    return value

async def get_cpt(chart_text, trace_id, patientId):
    logger.info("[CPT] Processing started trace_id=%s patient=%s", trace_id, patientId)
    response = await ai_call(chart_text, prompt)
    response = json_clean(response)
    logger.info("[CPT] Processing completed trace_id=%s patient=%s results=%d", trace_id, patientId, len(response) if isinstance(response, list) else 0)
    return response

async def cpt_coder(text, custom_prompt, patientId):
    logger.info("[CPT] Custom prompt processing started patient=%s", patientId)
    response = await ai_call(text, custom_prompt)
    response = json_clean(response)
    logger.info("[CPT] Custom prompt completed patient=%s results=%d", patientId, len(response) if isinstance(response, list) else 0)
    return response
