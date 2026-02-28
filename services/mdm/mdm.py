import json
import os
import re
import logging
from typing import Any, Dict
from dotenv import load_dotenv
from services.mdm.full_output_validater import Tab_1, Tab_2, Tab_3
from utils.ai import ai_call
from services.mdm.visitprompt import  prompt as visitprompt

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def json_clean(text):
    if not isinstance(text, str):
        return text, None

    explain = None
    fenced = re.search(
        r"```(?:json)?\s*(.*?)```",
        text,
        flags=re.DOTALL | re.IGNORECASE
    )

    json_block = None

    if fenced:
        explain = text[:fenced.start()].strip()
        json_block = fenced.group(1).strip()
    else:
        candidate = text.strip()
        json_block = candidate

    json_block = re.sub(r"//.*", "", json_block)
    json_block = re.sub(r",(\s*[}\]])", r"\1", json_block)

    try:
        parsed = json.loads(json_block)
    except Exception as e:
        raise ValueError(f"Payload not consumable as JSON: {e} text:{text[:200]}")

    return parsed, explain


def finallevel_calculator(table1_level, table2_level, table3_level):
    levels = sorted([
        table1_level.lower(),
        table2_level.lower(),
        table3_level.lower()
    ])
    return levels[1]

def answeroutput(table1, table2, table3):
    logger.info(f"Table 1 Level : {table1['MDM_Complexity_Level']['Level']}")
    logger.info(f"Table 2 Level : {table2['data_level']}")
    logger.info(f"Table 3 Level : {table3['risk_level']}")

    acute = table1.get('acute', [])
    chronic = table1.get('chronic', [])

    acute_item = acute[0] if acute else {}
    chronic_item = chronic[0] if chronic else {}

    table1output = {
        "patientType": table1.get("patientType", ""),
        "stable chronic illness": len(chronic) if chronic else None,
        "stable acute illness": len(acute) if acute else None,
        "problemsLevel": table1["MDM_Complexity_Level"].get("Level", "Straightforward"),
        "stable chronic illness exactSentence": chronic_item.get("exactSentence", ""),
        "stable acute illness exactSentence": acute_item.get("exactSentence", ""),
        "acutepageno": acute_item.get("PageNo"),
        "chronicpageno": chronic_item.get("PageNo"),
        "explain": table1["MDM_Complexity_Level"].get("Explain", "")
    }

    table2output = {
        "dataLevel": table2.get("data_level", "Straightforward"),
        "unique_laboratory_tests_count": table2.get("unique_laboratory_tests_count"),
        "exactSentence": table2.get("exactSentence", ""),
        "pageno": table2.get("PageNo"),
        "explain": table2.get("explain", "")
    }

    table3output = {
        "riskLevel": table3.get("risk_level", "Straightforward"),
        "Prescription drug management": "yes" if table3.get("risk_analysis") else "no",
        "exactSentence": table3.get("exactSentence", ""),
        "pageno": table3.get("PageNo"),
        "explain": table3.get("explain", "")
    }

    finallevel = finallevel_calculator(
        table1output["problemsLevel"],
        table2output["dataLevel"],
        table3output["riskLevel"]
    )

    return {
        "A": table1output,
        "B": table2output,
        "C": table3output,
        "finallevel": finallevel,
        "A_level": table1["MDM_Complexity_Level"]["Level"],
        "B_level": table2["data_level"],
        "C_level": table3["risk_level"],
        "table1_explain": table1output["explain"],
        "table2_explain": table2output["explain"],
        "table3_explain": table3output["explain"]
    }
def tab_a_exact(table):
    return [{
        "condition": i.get("condition", ""),
        "hyperLink": i.get("exactSentence", ""),
        "pageNumber": str(i.get("PageNo", 0)),
        "explanation": i.get("explain", "")
    } for i in table]
True

def tab_b_exact(table):
    return [{
        "condition": i.get("item", ""),
        "hyperLink": i.get("evidence_sentence", ""),
        "pageNumber": str(i.get("PageNo", 0)),
        "explanation": i.get("explain", "")
    } for i in table]

def tab_c_exact(table):
    return [{
        "condition": i.get("drug", ""),
        "hyperLink": i.get("evidence_sentence", ""),
        "pageNumber": str(i.get("PageNo", 0)),
        "explanation": i.get("explain", "")
    } for i in table.get("risk_analysis", [])]


def final_return(
    A, B, C,
    finallevel,
    A_level, B_level, C_level,
    table1explain, table2explain, table3explain,
    tableA, tableB, tableC,
    visitType
) -> Dict[str, Any]:

    final_level = (finallevel or "").lower()
    patient_type = A.get("patientType", "").lower()

    cpt_map = {
        "straightforward": ("99212", "99202"),
        "low": ("99213", "99203"),
        "moderate": ("99214", "99204"),
        "high": ("99215", "99205")
    }

    cpt_code = cpt_map.get(final_level, ("", ""))[0 if patient_type == "established" else 1]

    acute_count = A.get("stable acute illness")
    chronic_count = A.get("stable chronic illness")
    order_count = B.get("unique_laboratory_tests_count")

    valueOrder = bool(order_count)
    pre_drug = C.get("Prescription drug management") == "yes"

    if "Inpatient".lower()==visitType.get("visit_type","").lower():
        logger.info(f"Inpatient visitType ")
        cpt_code=visitType.get("cpt_code")
   
    elif "Emergency".lower()==visitType.get("visit_type","").lower():
        logger.info(f"Emergency visitType ")
        cpt_code=visitType.get("cpt_code")

    elif "Consult".lower()==visitType.get("visit_type","").lower():
        logger.info(f"Consult visitType ")
        cpt_code=visitType.get("cpt_code")

    elif "Preventive".lower()==visitType.get("visit_type","").lower():
        logger.info(f"Preventive visitType ")
        cpt_code=visitType.get("cpt_code")

    elif "Telehealth".lower()==visitType.get("visit_type","").lower():
        logger.info(f"Telehealth visitType ")
        cpt_code=visitType.get("cpt_code")

    elif "Facility".lower()==visitType.get("visit_type","").lower():
        logger.info(f"Facility visitType ")
        cpt_code=visitType.get("cpt_code")

    elif "Critical".lower()==visitType.get("visit_type","").lower():
        logger.info(f"Critical visitType ")
        cpt_code=visitType.get("cpt_code")
    
    else:
        logger.info(f"Office visitType ")
        cpt_code=cpt_code

    output={
        "finalLevel": finallevel,
        "cptCode": cpt_code,
        "patientType": A.get("patientType", "").upper(),
        "modifiers": [],
        "problems": {
            "explanation": table1explain,
            "level": A_level,
            "problems": [
                {
                    "name": "stable chronic illness",
                    "status": bool(chronic_count),
                    "count": chronic_count,
                    "medicalReportHyperLink": tab_a_exact(tableA.get("chronic", []))
                },
                {
                    "name": "stable acute illness",
                    "status": bool(acute_count),
                    "count": acute_count,
                    "medicalReportHyperLink": tab_a_exact(tableA.get("acute", []))
                }
            ]
        },

        "data": {
            "explanation": table2explain,
            "level": B_level,
            "problems": [
                {
                "name": "Ordering of each unique test",
                "status": valueOrder,
                "count": order_count,
                "medicalReportHyperLink": tab_b_exact(tableB.get("order_analysis", []))
                }
            ]
        },

        "risk": {
            "explanation": table3explain,
            "level": C_level,
            "problems": [
                {
                "name": "Prescription drug management",
                "status": pre_drug,
                "count": len(tableC.get("risk_analysis", [])),
                "medicalReportHyperLink": tab_c_exact(tableC)
                }
            ]
        }
    }
    logger.info(f"Final Output {output}")
    return output
import asyncio

async def safe_ai_call(text, prompt,timeout=600):
    try:
        return await asyncio.wait_for(
            ai_call(text, prompt),timeout=timeout
        )
    except asyncio.TimeoutError:
        logger.error("QWEN timeout")
        raise

async def output(text: str, trace_id: str) -> dict:
    logger.info(f"[QWEN]AI for send -> to ai MDM{trace_id}")

    visitType, tab_1_raw, tab_2_raw, tab_3_raw = await asyncio.gather(
    safe_ai_call(text,visitprompt),
    safe_ai_call(text, Tab_1),
    safe_ai_call(text, Tab_2),
    safe_ai_call(text, Tab_3),
)
    logger.info(f"[QWEN]AI for Income{trace_id}")

    try:
        tab_1_json, _ = await json_clean(tab_1_raw)
    except Exception as e:
        logger.exception("Tab 1 JSON parsing failed")
        raise
    try:
        tab_2_json, _ = await json_clean(tab_2_raw)
    except Exception as e:
        logger.exception("Tab 2 JSON parsing failed")
        raise
    try:
        tab_3_json, _ = await json_clean(tab_3_raw)
    except Exception as e:
        logger.exception("Tab 3 JSON parsing failed")
        raise
    try:
        visitType_json,_=await json_clean(visitType)
    except Exception as e:
        logger.exception("visitType JSON parsing failed")
        raise
    

    intermediate = answeroutput(tab_1_json, tab_2_json, tab_3_json)

    final_output = final_return(
        intermediate["A"],
        intermediate["B"],
        intermediate["C"],
        intermediate["finallevel"],
        intermediate["A_level"],
        intermediate["B_level"],
        intermediate["C_level"],
        intermediate["table1_explain"],
        intermediate["table2_explain"],
        intermediate["table3_explain"],
        tab_1_json,
        tab_2_json,
        tab_3_json,
        visitType_json
    )

    logger.info(f"MDM full final output for trace_id {trace_id}")
    return final_output

async def get_mdm(text, trace_id: str):
    return await output(text, trace_id)


async def mdm_test(text):
    return await output(text, trace_id="testing")
