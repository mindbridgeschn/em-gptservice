import os
import json
import re
import duckdb
import aiohttp
import asyncio
import logging
from services.icd.icd_prompt import prompt
from utils.ai import ai_call

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SYNONYM_DB_PATH = os.path.join(BASE_DIR, 'icd_synonym2026_1.duckdb')
MAIN_DB_PATH = os.path.join(BASE_DIR, 'icd_2026.duckdb')
SYNONYM_DB = os.getenv('SYNONYM_DB', SYNONYM_DB_PATH)
MAIN_DB = os.getenv('MAIN_DB', MAIN_DB_PATH)

if not os.path.exists(SYNONYM_DB):
    logger.warning("[ICD] Synonym database not found path=%s", SYNONYM_DB)
if not os.path.exists(MAIN_DB):
    logger.warning("[ICD] Main database not found path=%s", MAIN_DB)

def parse_json_strict(s: str):
    s = re.sub(r"<think>.*?</think>", "", s, flags=re.DOTALL).strip()
    if s.startswith("```"):
        s = s.strip("`")
        if s.startswith("json"):
            s = s[len("json"):].strip()
    return json.loads(s)

def remove_dots_from_icd(icd_code):
    return icd_code.replace(".", "") if icd_code else ""


async def find_condition_in_synonym_table(condition):
    try:
        with duckdb.connect(SYNONYM_DB) as conn:
            query = "SELECT ICD FROM icd_synonym2026_1 WHERE LOWER(DESCRIPTION) = LOWER(?) LIMIT 1"
            result = conn.execute(query, [condition]).fetchone()
            if result:
                return result[0]

            query = "SELECT ICD FROM icd_synonym2026_1 WHERE LOWER(DESCRIPTION) LIKE LOWER(?) LIMIT 1"
            result = conn.execute(query, [f"%{condition}%"]).fetchone()
            if result:
                return result[0]
        return None
    except Exception as e:
        logger.error("[ICD] Synonym table search failed condition=%s error=%s", condition, e)
        return None

async def find_icd_in_main_table(icd_code):
    try:
        search_code = remove_dots_from_icd(icd_code)
        with duckdb.connect(MAIN_DB) as conn:
            query = "SELECT ICD, DESCRIPTION FROM icd_2026 WHERE REPLACE(ICD, '.', '') = ? LIMIT 1"
            result = conn.execute(query, [search_code]).fetchone()
            if result:
                return (result[0], result[1])
        return None
    except Exception as e:
        logger.error("[ICD] Main table search failed icd_code=%s error=%s", icd_code, e)
        return None

async def map_condition_to_icd(condition, qwen_icd_code, qwen_icd_description):
    if not condition:
        logger.warning("[ICD] Empty condition provided, falling back to AI output")
        return {
            "icd_code": remove_dots_from_icd(qwen_icd_code) if qwen_icd_code else "",
            "icd_description": qwen_icd_description or "",
            "source": "qwen"
        }

    synonym_icd_code = await find_condition_in_synonym_table(condition)
    if synonym_icd_code:
        logger.info("[ICD] Synonym match found condition=%s icd=%s", condition, synonym_icd_code)
        main_table_result = await find_icd_in_main_table(synonym_icd_code)
        if main_table_result:
            logger.info("[ICD] Main table verified icd=%s source=database", synonym_icd_code)
            return {
                "icd_code": remove_dots_from_icd(main_table_result[0]),
                "icd_description": main_table_result[1],
                "source": "database"
            }
        else:
            logger.info("[ICD] ICD %s not in main table, using AI output", synonym_icd_code)
    else:
        logger.info("[ICD] No synonym match for condition=%s, using AI output", condition)

    qwen_code = remove_dots_from_icd(qwen_icd_code) if qwen_icd_code else ""
    return {
        "icd_code": qwen_code,
        "icd_description": qwen_icd_description or "",
        "source": "qwen"
    }

async def get_icd(text, trace_id: str):
    logger.info("[ICD] Processing started trace_id=%s", trace_id)
    try:
        llm_output = await ai_call(text, prompt)
        qwen_output = parse_json_strict(llm_output)
        logger.info("[ICD] AI response parsed trace_id=%s", trace_id)

        if not isinstance(qwen_output, dict):
            logger.error("[ICD] AI response is not a valid JSON object trace_id=%s", trace_id)
            return {
                "primary_condition": None,
                "secondary_condition": None,
                "error": "LLM response is not a valid JSON object"
            }

        if "primary_condition" not in qwen_output:
            logger.error("[ICD] Missing primary_condition in AI response trace_id=%s", trace_id)
            return {
                "primary_condition": None,
                "secondary_condition": None,
                "error": "Missing primary_condition in LLM response"
            }

        enhanced_output = {"primary_condition": None, "secondary_condition": None}

        # Primary condition
        if qwen_output.get("primary_condition"):
            primary = qwen_output["primary_condition"]
            if primary and primary.get("condition"):
                mapped_primary = await map_condition_to_icd(
                    primary.get("condition", ""),
                    primary.get("icd_code", ""),
                    primary.get("icd_description", "")
                )
                if mapped_primary.get("icd_code"):
                    enhanced_output["primary_condition"] = {
                        "icd_code": mapped_primary["icd_code"],
                        "icd_description": mapped_primary["icd_description"],
                        "is_primary": True,
                        "hyperLink": primary.get("hyperLink", {})
                    }
                    logger.info("[ICD] Primary condition mapped source=%s icd=%s", mapped_primary['source'], mapped_primary['icd_code'])
                else:
                    logger.warning("[ICD] Primary condition mapping returned empty ICD code")

        # Secondary condition(s)
        if qwen_output.get("secondary_condition"):
            secondary_data = qwen_output["secondary_condition"]
            enhanced_output["secondary_condition"] = []

            if isinstance(secondary_data, list):
                for sec in secondary_data:
                    if sec and sec.get("condition"):
                        mapped_secondary = await map_condition_to_icd(
                            sec.get("condition", ""),
                            sec.get("icd_code", ""),
                            sec.get("icd_description", "")
                        )
                        if mapped_secondary.get("icd_code"):
                            enhanced_output["secondary_condition"].append({
                                "icd_code": mapped_secondary["icd_code"],
                                "icd_description": mapped_secondary["icd_description"],
                                "is_primary": False,
                                "hyperLink": sec.get("hyperLink", {})
                            })
                            logger.info("[ICD] Secondary condition mapped source=%s icd=%s", mapped_secondary['source'], mapped_secondary['icd_code'])
                        else:
                            logger.warning("[ICD] Secondary mapping empty ICD code condition=%s", sec.get('condition'))
            else:
                if secondary_data and secondary_data.get("condition"):
                    mapped_secondary = await map_condition_to_icd(
                        secondary_data.get("condition", ""),
                        secondary_data.get("icd_code", ""),
                        secondary_data.get("icd_description", "")
                    )
                    if mapped_secondary.get("icd_code"):
                        enhanced_output["secondary_condition"] = [{
                            "icd_code": mapped_secondary["icd_code"],
                            "icd_description": mapped_secondary["icd_description"],
                            "is_primary": False,
                            "hyperLink": secondary_data.get("hyperLink", {})
                        }]
                        logger.info("[ICD] Secondary condition mapped source=%s icd=%s", mapped_secondary['source'], mapped_secondary['icd_code'])
                    else:
                        logger.warning("[ICD] Secondary mapping empty ICD code condition=%s", secondary_data.get('condition'))

        if enhanced_output.get("secondary_condition") == []:
            enhanced_output["secondary_condition"] = None

        primary_code = enhanced_output["primary_condition"]["icd_code"] if enhanced_output.get("primary_condition") else "none"
        secondary_count = len(enhanced_output["secondary_condition"]) if enhanced_output.get("secondary_condition") else 0
        logger.info("[ICD] Processing completed trace_id=%s primary=%s secondary_count=%d", trace_id, primary_code, secondary_count)
        return enhanced_output

    except asyncio.TimeoutError:
        logger.error("[ICD] AI request timed out trace_id=%s", trace_id)
        return {
            "primary_condition": None,
            "secondary_condition": None,
            "error": "LLM API request timed out. Please try again."
        }
    except aiohttp.ClientConnectionError:
        logger.error("[ICD] Cannot connect to AI API trace_id=%s", trace_id)
        return {
            "primary_condition": None,
            "secondary_condition": None,
            "error": "Cannot connect to LLM API. Please check the API host and port."
        }
    except Exception as e:
        logger.error("[ICD] Processing failed trace_id=%s error=%s", trace_id, e)
        return {
            "primary_condition": None,
            "secondary_condition": None,
            "error": f"An unexpected error occurred: {str(e)}"
        }
