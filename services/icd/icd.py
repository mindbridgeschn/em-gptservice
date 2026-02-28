import os
import json
import re
import duckdb
import aiohttp
import asyncio
import logging
from services.icd.icd_prompt import prompt
from utils.ai import ai_call
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(message)s"
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SYNONYM_DB_PATH = os.path.join(BASE_DIR, 'icd_synonym2026_1.duckdb')
MAIN_DB_PATH = os.path.join(BASE_DIR, 'icd_2026.duckdb')
SYNONYM_DB = os.getenv('SYNONYM_DB', SYNONYM_DB_PATH)
MAIN_DB = os.getenv('MAIN_DB', MAIN_DB_PATH)

# Verify database files exist
if not os.path.exists(SYNONYM_DB):
    logging.warning(f"Synonym database not found at: {SYNONYM_DB}")
if not os.path.exists(MAIN_DB):
    logging.warning(f"Main database not found at: {MAIN_DB}")

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
        logging.info(f"Error searching synonym table: {e}")
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
        logging.info(f"Error searching main ICD table: {e}")
        return None

async def map_condition_to_icd(condition, qwen_icd_code, qwen_icd_description):
    if not condition:
        logging.warning("Empty condition provided to map_condition_to_icd")
        return {
            "icd_code": remove_dots_from_icd(qwen_icd_code) if qwen_icd_code else "",
            "icd_description": qwen_icd_description or "",
            "source": "qwen"
        }
    
    synonym_icd_code = await find_condition_in_synonym_table(condition)
    if synonym_icd_code:
        logging.info(f"Found condition '{condition}' in synonym table → ICD: {synonym_icd_code}")
        main_table_result = await find_icd_in_main_table(synonym_icd_code)
        if main_table_result:
            logging.info(f"Found ICD code {synonym_icd_code} in main table")
            return {
                "icd_code": remove_dots_from_icd(main_table_result[0]),
                "icd_description": main_table_result[1],
                "source": "database"
            }
        else:
            logging.info(f"ICD code {synonym_icd_code} not found in main table → using Qwen output")
    else:
        logging.info(f"Condition '{condition}' not found in synonym table → using Qwen output")

    # Fallback to Qwen output
    qwen_code = remove_dots_from_icd(qwen_icd_code) if qwen_icd_code else ""
    return {
        "icd_code": qwen_code,
        "icd_description": qwen_icd_description or "",
        "source": "qwen"
    }

async def get_icd(text, trace_id: str):
    try:
        logging.info(f"ICD text for trace_id: {trace_id}")
        llm_output = await ai_call(text, prompt)
        qwen_output = parse_json_strict(llm_output)
        logging.info(f"ICD Qwen output for trace_id: {trace_id}: {qwen_output}")
        if not isinstance(qwen_output, dict):
            return {
                "primary_condition": None,
                "secondary_condition": None,
                "error": "LLM response is not a valid JSON object"
            }
        logging.info(f"ICD primary condition for trace_id: {trace_id}: {qwen_output.get('primary_condition')}")
        if "primary_condition" not in qwen_output:
            return {
                "primary_condition": None,
                "secondary_condition": None,
                "error": "Missing primary_condition in LLM response"
            }
        logging.info(f"ICD secondary condition for trace_id: {trace_id}: {qwen_output.get('secondary_condition')}")
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
                    logging.info(f"Primary condition mapped by: {mapped_primary['source']}")
                else:
                    logging.warning("Primary condition mapping resulted in empty ICD code")

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
                            logging.info(f"Secondary condition mapped by: {mapped_secondary['source']}")
                        else:
                            logging.warning(f"Secondary condition '{sec.get('condition')}' mapping resulted in empty ICD code")
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
                        logging.info(f"Secondary condition mapped by: {mapped_secondary['source']}")
                    else:
                        logging.warning(f"Secondary condition '{secondary_data.get('condition')}' mapping resulted in empty ICD code")

        if enhanced_output.get("secondary_condition") == []:
            enhanced_output["secondary_condition"] = None
        
        logging.info(f"ICD enhanced output for trace_id: {trace_id}: {enhanced_output}")
        return enhanced_output

    except asyncio.TimeoutError:
        logging.info("LLM API request timed out")
        return {
            "primary_condition": None,
            "secondary_condition": None,
            "error": "LLM API request timed out. Please try again."
        }
    except aiohttp.ClientConnectionError:
        logging.info("Cannot connect to LLM API")
        return {
            "primary_condition": None,
            "secondary_condition": None,
            "error": "Cannot connect to LLM API. Please check the API host and port."
        }
    except Exception as e:
        logging.info(f"Unexpected error: {e}")
        return {
            "primary_condition": None,
            "secondary_condition": None,
            "error": f"An unexpected error occurred: {str(e)}"
        }