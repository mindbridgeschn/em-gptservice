import json
import logging
from dotenv import load_dotenv
#from services.cpt.emb_cpt.prompt_store import load_prompts
from utils.ai import ai_call
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)
logger = logging.getLogger("cpt-rag-service")
load_dotenv()

logger.warning("Prompts loaded successfully")

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
            return []

    return value

#from services.duck.duck_store import save_rag_log
#from services.cpt.emb_cpt.prompt_store import DEFAULT_PROMPTS
#fp = DEFAULT_PROMPTS["first_prompt"][:100]
#logger.warning(f"First prompt loaded successfully {fp}")
from services.cpt.cpt_prompt import prompt 
async def get_cpt(chart_text,prompt,patientId):
    response = await ai_call(chart_text,prompt)
    response = json_clean(response)

    return response

# ==================== Testing Chart ==============

async def cpt_coder(text,prompt,patientId):
    response=await get_cpt(text,prompt=prompt,patientId=patientId)
    return response 