import json
import logging
from typing import List, Optional
from pydantic import BaseModel
from utils.ai import ai_call
from services.hcpcs.hcpcs_prompt import prompt

logger = logging.getLogger(__name__)

class HcpcsResult(BaseModel):
    hcpcs_code: str
    description: str
    evidence_sentence: Optional[str] = None
    page_number: Optional[int] = None

class ApiResponse(BaseModel):
    drugs_extracted: List[HcpcsResult]

async def json_clean(text):
    if isinstance(text, str):
        text = text.strip()
        if text.startswith("```json"):
            text = text.replace("```json", "").replace("```", "").strip()
        try:
            text = json.loads(text)
        except json.JSONDecodeError:
            logger.warning("[HCPCS] Failed to parse AI response as JSON")
            text = []
    return text


async def get_hcpcs(request_text: str, trace_id: str):
    logger.info("[HCPCS] Processing started trace_id=%s", trace_id)
    ai_output = await ai_call(request_text, prompt)
    cleaned = await json_clean(ai_output)
    logger.info("[HCPCS] Processing completed trace_id=%s results=%d", trace_id, len(cleaned) if isinstance(cleaned, list) else 0)
    return cleaned
