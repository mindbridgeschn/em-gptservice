import asyncio
import json
import os
import requests
from dotenv import load_dotenv
from typing import Dict, List, Tuple, Union, Any
from services.mdm.mdm_promptfinal import mdm_prompt
from utils.ai import ai_call_qwen
import logging

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def json_clean(text):
    if isinstance(text, str):
        text = text.strip()
        if text.startswith("```json"):
            text = text.replace("```json", "").replace("```", "").strip()
        try:
            text = json.loads(text)
        except json.JSONDecodeError:
            text = []
    return text

PROLOG_PROBLEM_LABELS = {
    "SLM": "self-limited or minor problem",
    "SCI": "stable chronic illness",
    "AUI": "acute, uncomplicated illness or injury",
    "SAI": "stable acute illness",
    "AUIO": "acute, uncomplicated illness or injury requiring hospital inpatient or observation level of care",
    "CIE": "chronic illnesses with exacerbation, progression, or side effects of treatment",
    "UNP": "undiagnosed new problem with uncertain prognosis",
    "AIS": "acute illness with systemic symptoms",
    "ACI": "acute complicated injury",
    "CISE": "chronic illnesses with severe exacerbation, progression, or side effects of treatment",
    "TLF": "acute or chronic illness or injury that poses a threat to life or bodily function"
}

PROLOG_CONDITION_LABELS = {
    "minRisk": "Minimal risk of morbidity from additional diagnostic testing or treatment",
    "lowRisk": "Low risk of morbidity from additional diagnostic testing or treatment",
    "rxMgmt": "Prescription drug management",
    "minSurgRisk": "Decision regarding minor surgery with identified patient or procedure risk factors",
    "majSurgNoRisk": "Decision regarding elective major surgery without identified patient or procedure risk factors",
    "sdohLimit": "Diagnosis or treatment significantly limited by social determinants of health",
    "toxMonitor": "Drug therapy requiring intensive monitoring for toxicity",
    "majSurgWithRisk": "Decision regarding elective major surgery with identified patient or procedure risk factors",
    "emergSurg": "Decision regarding emergency major surgery",
    "hospEscalate": "Decision regarding hospitalization or escalation of hospital-level care",
    "dnr": "Decision not to resuscitate or to de-escalate care because of poor prognosis",
    "ivControlled": "Parenteral controlled substances"
}

PROLOG_RISKS_LABELS = {
    "NM": "None or Minimal",
    "RENOTE": "Review of prior external note(s) from each unique source",
    "RTEST": "Review of the result(s) of each unique test",
    "OTEST": "Ordering of each unique test",
    "IHIST": "Assessment requiring an independent historian(s)",
    "IINTERP": "Independent interpretation of a test performed by another physician/other qualified health care professional (not separately reported)",
    "DMEXT": "Discussion of management or test interpretation with external physician/other qualified health care professional/appropriate source (not separately reported)"
}

PROLOG_PROBLEM_MAP = {
    "SLM": "self_limited_minor", "SCI": "stable_chronic", "AUI": "acute_uncomplicated",
    "SAI": "stable_acute", "AUIO": "acute_uncomplicated_hospital", "CIE": "chronic_exacerbation",
    "UNP": "undiagnosed_new", "AIS": "acute_systemic", "ACI": "acute_complicated_injury",
    "CISE": "chronic_severe", "TLF": "threatening_illness"
}

CPT_MAP = {
    "new": {
        "straightforward": "99202", "low": "99203", "moderate": "99204", "high": "99205"
    },
    "established": {
        "straightforward": "99212", "low": "99213", "moderate": "99214", "high": "99215"
    }
}

RANK_TO_LABEL = {1: "straightforward", 2: "low", 3: "moderate", 4: "high"}
LABEL_TO_RANK = {v: k for k, v in RANK_TO_LABEL.items()}

# Prolog table files - adjust paths to your environment
FILE_TAB1 = os.getenv("FILE_TAB1", "services/mdm/tables/table1.pl")
FILE_TAB2 = os.getenv("FILE_TAB2", "services/mdm/tables/table2.pl")
FILE_TAB3 = os.getenv("FILE_TAB3", "services/mdm/tables/table3.pl")
#FILE_TAB1 = os.getenv("FILE_TAB1", "C:/Users/encip/E_M/mdm/tables/table1.pl")
#FILE_TAB2 = os.getenv("FILE_TAB2", "C:/Users/encip/E_M/mdm/tables/table2.pl")
#FILE_TAB3 = os.getenv("FILE_TAB3", "C:/Users/encip/E_M/mdm/tables/table3.pl")

async def get_label(section_type: str, key: str) -> str:
    if section_type == "conditions":
        return PROLOG_CONDITION_LABELS.get(key, key)
    elif section_type == "risk":
        return PROLOG_RISKS_LABELS.get(key, key)
    elif section_type == "problems":
        return PROLOG_PROBLEM_LABELS.get(key, key)
    return key

async def transform_section(section: Any, section_type: str, hyperlinks: Dict[str, dict] = None) -> List[dict]:
    if section is None:
        return []

    transformed = []
    if isinstance(section, dict):
        entries = [section]
    elif isinstance(section, list):
        entries = section
    else:
        return []

    for entry in entries:
        if not isinstance(entry, dict):
            continue

        for key, val in entry.items():
            if key in ("name", "count"):
                continue

            new_entry = {
                "name": await get_label(section_type, key),
                "value": None,
                "count": None,
                "exactSentence": "",
                "page": ""
            }
            if isinstance(val, int) and val != 0:
                new_entry["count"] = str(val)
            else:
                val_str = str(val).strip()

                if val_str.lower() in ["", "no", "0", "false", "none"]:
                    new_entry["value"] = None
                else:
                    new_entry["value"] = val_str

            # Attach evidence and page if given
            if hyperlinks and key in hyperlinks:
                link_data = hyperlinks[key]
                new_entry["exactSentence"] = link_data.get("exact_sentence") or link_data.get("exactSentence", "")
                new_entry["page"] = link_data.get("page", "")

            transformed.append(new_entry)

    return transformed

async def run_remote_prolog(command: Union[str, Tuple[str, str]]) -> Tuple[bool, str]:
    print(command)
    PROLOG_API_URL = os.getenv("PROLOG_API_URL")

    if isinstance(command, tuple) and len(command) == 2:
        program, query = command
    else:
        program, query = "", str(command)
    if not query.strip().endswith('.'):
        query = query.strip() + '.'
    payload = {"program": program, "query": query}

    try:
        r = requests.post(PROLOG_API_URL, json=payload, timeout=60)
        if r.status_code != 200:
            return False, f"HTTP {r.status_code}"

        data = r.json()
        print(data)
        if "results" in data:
            results = data["results"]
            if not results:
                return False, "empty results"

            first = results[0]

            # Case 1: dict like {"Max": "moderate"}
            if isinstance(first, dict):
                val = next(iter(first.values()), None)
                return True, str(val) if val else "unknown"

            # Case 2: plain string like "moderate"
            if isinstance(first, str):
                return True, first

            # Case 3: weird structure (list of lists or bools)
            return True, str(first)

        if "output" in data:
            return True, str(data["output"])

        return False, "Unexpected response format"
    except Exception as e:
        logger.error(f"Remote prolog error: {e}")
        return False, str(e)



async def table1(problems: List[Tuple[str, int]], file_path: str = FILE_TAB1) -> str:
    print(problems,"massss")
    with open(file_path, "r") as f:
        prolog_program = f.read()
    if not problems:
        return "straightforward"
    try:
        prolog_terms = []
        for code, count in problems:
            prolog_atom = PROLOG_PROBLEM_MAP.get(code.upper(), "self_limited_minor")
            prolog_terms.append(f"('{prolog_atom}', {count})")
        prolog_list = "[" + ", ".join(prolog_terms) + "]"
        query = f"highest_complexity_from_list({prolog_list}, Max)."
        command = f"consult('{file_path}'), {query}"
        #ok, out = run_prolog_command(command)
        ok, out = await run_remote_prolog((prolog_program, query))
        if not ok or not out:
            logger.info("table1 fallback to 'straightforward' (prolog missing or empty). out=%s", out)
            return "straightforward"
        print("table1:", ok, out)
        return out.strip().lower()
    except Exception as e:
        logger.exception("table1 failed")
        return "straightforward"

async def table2(a: int, b: int, c: int, d: int, e: int, f: int, g: int) -> str:
    try:
        b_adj = min(c, 2)
        c_adj = min(d, 2)
        def mo(a_, b_, c_, d_, e_, f_):
            a_ = min(a_, 3)
            b_ = min(b_, 3)
            c_ = min(c_, 3)
            cat1 = min(a_, 3) + min(b_, 3) + min(c_, 3) + (1 if d_ > 0 else 0)
            if a_ == 0 and b_ == 0 and c_ == 0 and d_ == 1 and e_ == 0 and f_ == 0:
                return "low"
            has_E = e_ > 0
            has_F = f_ > 0
            if cat1 == 0 and not has_E and not has_F:
                return "straightforward"
            if cat1 >= 3 and (has_E or has_F):
                return "high"
            if has_E and has_F:
                return "high"
            if cat1 >= 3 or has_E or has_F:
                return "moderate"
            if cat1 == 2:
                return "low"
            return "straightforward"
        res = mo(a, b_adj, c_adj, d, e, f)
        print("table2:", res)
        return res
    except Exception as e:
        logger.exception(f"table2 encountered an error, defaulting to straightforward: {e}")
        return "straightforward"
table_3={
    "MINRISK": "minimal_risk_of_morbidity",
    "LOWRISK": "low_risk_of_morbidity",
    "RXMGMT": "prescription_drug_management",
    "MINSURGRISK": "minor_surgery_with_risk_factors",
    "MAJSURGNORISK": "elective_major_surgery_without_risk_factors",
    "SDOHLIMIT": "sdh_limiting_diagnosis_or_treatment",
    "TOXMONITOR": "drug_therapy_intensive_monitoring",
    "MAJSURGWITHRISK": "elective_major_surgery_with_risk_factors",
    "EMERGSURG": "emergency_major_surgery",
    "HOSPESCALATE": "hospitalization_or_escalation",
    "DNR": "do_not_resuscitate_due_to_poor_prognosis",
    "IVCONTROLLED": "parenteral_controlled_substances"
}
async def table3(conditions: List[str], file_path: str = FILE_TAB3) -> str:
    with open(file_path, "r") as f:
        prolog_program = f.read()
    if not conditions:
        return "straightforward"
    conditions = [table_3[key] for key in conditions]
    try:
        prolog_list = "[" + ", ".join(conditions) + "]"
        query = f"max_risk({prolog_list}, Max)."
        command = f"consult('{file_path}'), {query}"
        #ok, out = run_prolog_command(command)
        ok, out = await run_remote_prolog((prolog_program, query))
        if not ok or not out:
            logger.info("table3 fallback to 'straightforward' (prolog missing or empty). out=%s", out)
            return "straightforward"
        print("table3:", out)
        return out.strip().lower()
    except Exception:
        logger.exception("table3 failed")
        return "straightforward"

async def re_table(risk: List[Tuple[str, Union[str, int]]]) -> Tuple[List[Tuple[str, int]], List[int]]:
    new_tab2 = []
    numeric_values = []
    for key, val in risk:
        if key == "NM":
            mapped_val = 0 if str(val).lower() == "no" else 1
            new_tab2.append(("a", mapped_val))
            numeric_values.append(mapped_val)
        elif key == "RENOTE":
            if isinstance(val, str):
                mapped_val = 1 if val.lower() == "yes" else 0
            else:
                mapped_val = int(val)
            new_tab2.append(("b", mapped_val))
            numeric_values.append(mapped_val)
        elif key == "RTEST":
            try:
                mapped_val = int(val)
            except Exception:
                mapped_val = 0
            new_tab2.append(("c", mapped_val))
            numeric_values.append(mapped_val)
        elif key == "OTEST":
            if isinstance(val, int):
                mapped_val = val
            else:
                mapped_val = 1 if str(val).lower() in ("yes", "true", "1") else 0
            new_tab2.append(("d", mapped_val))
            numeric_values.append(mapped_val)
        elif key == "IHIST":
            mapped_val = 1 if str(val).lower() in ("yes", "true", "1") else 0
            new_tab2.append(("e", mapped_val))
            numeric_values.append(mapped_val)
        elif key == "IINTERP":
            mapped_val = 1 if str(val).lower() in ("yes", "true", "1") else 0
            new_tab2.append(("f", mapped_val))
            numeric_values.append(mapped_val)
        elif key == "DMEXT":
            mapped_val = 1 if str(val).lower() in ("yes", "true", "1") else 0
            new_tab2.append(("g", mapped_val))
            numeric_values.append(mapped_val)
        else:
            continue
    return new_tab2, numeric_values


async def get_cpt_code(data, trace_id: str):
    try:
        payload = data
        problems = payload.get("problems", {}) or {}
        problem_terms = []
        for k, v in problems.items():
            if int(v) > 0:
                problem_terms.append((k.upper(), int(v)))

        risk_items = []
        for k, v in (payload.get("risk", {}) or {}).items():
            risk_items.append((k.upper(), str(v).lower() if isinstance(v, str) else v))

        _, numeric_risks = await re_table(risk_items)
        if len(numeric_risks) != 7:
            logger.warning("numeric_risks length != 7 (got %d). Padding with zeros.", len(numeric_risks))
            numeric_risks = (numeric_risks + [0] * 7)[:7]

        a, b, c, d, e, f, g = (int(v) for v in numeric_risks[:7])

        conditions = []
        for k, v in (payload.get("conditions", {}) or {}).items():
            try:
                if str(v).strip().lower() in ("yes", "true", "1"):
                    conditions.append(k.upper())
            except Exception:
                continue

        tab1_label = await table1(problem_terms)
        tab2_label = await table2(a, b, c, d, e, f, g)
        tab3_label = await table3(conditions)

        rank1 = LABEL_TO_RANK.get(tab1_label, LABEL_TO_RANK["straightforward"])
        rank2 = LABEL_TO_RANK.get(tab2_label.lower(), LABEL_TO_RANK["straightforward"])
        rank3 = LABEL_TO_RANK.get(tab3_label, LABEL_TO_RANK["straightforward"])

        combined = sorted([rank1, rank2, rank3])
        final_rank = combined[1]
        final_label = RANK_TO_LABEL.get(final_rank, "straightforward")
        print("final_label:", final_label)
        patient_type = (payload.get("patientType") or "").lower().strip()
        if patient_type not in ("new", "established"):
            patient_type = "new"
        cpt_code = CPT_MAP.get(patient_type, {}).get(final_label)
        #print("cpt_code:", cpt_code)
        result = {
            "tab1_label": tab1_label,
            "tab2_label": tab2_label,
            "tab3_label": tab3_label,
            "final_level": final_label,
            "cpt_code": cpt_code
        }

        logger.info(f"MDM get_cpt_code output for trace_id: {trace_id}: {result}")
        return result
        
    except Exception as e:
        logger.exception("get_cpt_code catastrophic failure")
        return {"error": str(e)}

async def mdm_r(data: Any, trace_id: str) -> Dict[str, Any]:
    result = await get_cpt_code(data, trace_id)
    logger.info(f"MDM mdm_r output for trace_id: {trace_id}: {result}")
    return result

async def output(text: str, trace_id: str) -> dict:
    raw_ai = await ai_call_qwen(text, mdm_prompt)
    raw_ai = await json_clean(raw_ai)

    ai = {}
    if isinstance(raw_ai, dict):
        ai = raw_ai

    exact_sentences = []
    for section_key in ["conditions_hyperlink", "risk_hyperlink", "problems_hyperlink"]:
        section = ai.get(section_key) or {}
        if isinstance(section, dict):
            for val in section.values():
                if isinstance(val, dict):
                    sentence = val.get("exact_sentence") or val.get("exactSentence") or ""
                    if sentence:
                        exact_sentences.append(sentence)

    ans = {
        "conditions":ai.get("conditions") or ai.get("condition") or {},
        "risk": ai.get("risk") or {},
        "problems": ai.get("problems") or {},
        "patientType": (ai.get("patientType") or "").strip() or None,
        "modifiers": [] if ai.get("patientType") else []
    }

    ans_table = await mdm_r(ans, trace_id)  
    final_output = {
        "problemsLevel": ans_table.get("tab1_label"),
        "riskLevel": ans_table.get("tab2_label"),
        "conditionLevel": ans_table.get("tab3_label"),
        "finalLevel": ans_table.get("final_level"),
        "patientType": (ai.get("patientType") or "").upper() if ai.get("patientType") else None,
        "modifiers": ans.get("modifiers") or [],
        "cptCode": ans_table.get("cpt_code"),
        "conditions": await transform_section(ans["conditions"], "conditions", ai.get("conditions_hyperlink")),
        "risk": await transform_section(ans["risk"], "risk", ai.get("risk_hyperlink")),
        "problems": await transform_section(ans["problems"], "problems", ai.get("problems_hyperlink")),
    }
    logger.info(f"MDM final output for trace_id: {trace_id}: {final_output}")
    return final_output

async def get_mdm(text, trace_id: str):
    result=await output(text, trace_id)
    print(result)
    logger.info(f"MDM result for trace_id: {trace_id}: {result}")
    return result
