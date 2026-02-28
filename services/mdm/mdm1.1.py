import asyncio
import json
import os
from unittest import result
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
    "MIN_RISK": "Minimal risk of morbidity from additional diagnostic testing or treatment",
    "LOW_RISK": "Low risk of morbidity from additional diagnostic testing or treatment",
    "RX_MGMT": "Prescription drug management",
    "MIN_SURG_RISK": "Decision regarding minor surgery with identified patient or procedure risk factors",
    "MAJ_SURG_NO_RISK": "Decision regarding elective major surgery without identified patient or procedure risk factors",
    "SDOH_LIMIT": "Diagnosis or treatment significantly limited by social determinants of health",
    "TOX_MONITOR": "Drug therapy requiring intensive monitoring for toxicity",
    "MAJ_SURG_WITH_RISK": "Decision regarding elective major surgery with identified patient or procedure risk factors",
    "EMERG_SURG": "Decision regarding emergency major surgery",
    "HOSP_ESCALATE": "Decision regarding hospitalization or escalation of hospital-level care",
    "DNR": "Decision not to resuscitate or to de-escalate care because of poor prognosis",
    "IV_CONTROLLED": "Parenteral controlled substances",
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
    "MIN_RISK": "minimal_risk_of_morbidity",
    "MINRISK": "minimal_risk_of_morbidity",
    "LOW_RISK": "low_risk_of_morbidity",
    "LOWRISK": "low_risk_of_morbidity",
    "RX_MGMT": "prescription_drug_management",
    "RXMGMT": "prescription_drug_management",
    "MIN_SURG_RISK": "minor_surgery_with_risk_factors",
    "MINSURGRISK": "minor_surgery_with_risk_factors",
    "MAJ_SURG_NO_RISK": "elective_major_surgery_without_risk_factors",
    "MAJSURGNORISK": "elective_major_surgery_without_risk_factors",
    "SDOH_LIMIT": "sdh_limiting_diagnosis_or_treatment",
    "SDOHLIMIT": "sdh_limiting_diagnosis_or_treatment",
    "TOX_MONITOR": "drug_therapy_intensive_monitoring",
    "TOXMONITOR": "drug_therapy_intensive_monitoring",
    "MAJ_SURG_WITH_RISK": "elective_major_surgery_with_risk_factors",
    "MAJSURGWITHRISK": "elective_major_surgery_with_risk_factors",
    "EMERG_SURG": "emergency_major_surgery",
    "EMERGSURG": "emergency_major_surgery",
    "HOSP_ESCALATE": "hospitalization_or_escalation",
    "HOSPESCALATE": "hospitalization_or_escalation",
    "DNR": "do_not_resuscitate_due_to_poor_prognosis",
    "IV_CONTROLLED": "parenteral_controlled_substances",
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
from services.mdm.mdm_validater import mdm_validator_prompt

async def validate_with_ai(chart_text: str, ai_json: dict) -> dict:
    payload = {
        "chart": chart_text,
        "ai_output": ai_json
    }
    raw = await ai_call_qwen(str(payload), mdm_validator_prompt)
    cleaned = await json_clean(raw)
    return cleaned if isinstance(cleaned, dict) else ai_json
from services.mdm.full_output_validater import prompt as full_output_validator_prompt

async def full_output(text: str, trace_id: str) -> dict:
    ai_valid= await ai_call_qwen(text, full_output_validator_prompt)
    ai_valid= await json_clean(ai_valid)
    if isinstance(ai_valid, dict):
        logger.info(f"MDM Full Validated AI output for trace_id: {trace_id}: {ai_valid}")
        return ai_valid

def final_return(output: dict, sec_output: dict) -> str:

    acute_count=sec_output.get("Table_A_Analysis",{}).get("acute_count","")
    chronic_count=sec_output.get("Table_A_Analysis",{}).get("chronic_count","")

    table_a_evidence_acute=sec_output.get("Table_A_Analysis",{}).get("evidence_sentance_acute","")
    table_a_evidence_chronic=sec_output.get("Table_A_Analysis",{}).get("evidence_sentance_chronic","")
    table_a_complexity=sec_output.get("Table_A_Analysis",{}).get("complexity_level","")
    table_a_acute_critical_condition=sec_output.get("Table_A_Analysis",{}).get("acute_critical_condition","")
    table_a_chronic_worsening=sec_output.get("Table_A_Analysis",{}).get("chronic_worsening","")

    orders_count=sec_output.get("Table_B_Analysis",{}).get("orders_count","")
    imaging_count=sec_output.get("Table_B_Analysis",{}).get("imaging_count","")
    table_b_evidence=sec_output.get("Table_B_Analysis",{}).get("evidence_sentance","")
    table_b_complexity=sec_output.get("Table_B_Analysis",{}).get("complexity_level","")

    current_medication_action=sec_output.get("Table_C_Analysis",{}).get("current_medication_action","")
    Otc_drug=sec_output.get("Table_C_Analysis",{}).get("Otc_drug","")
    physical_therapy=sec_output.get("Table_C_Analysis",{}).get("physical_therapy","")
    occupational_therapy=sec_output.get("Table_C_Analysis",{}).get("occupational_therapy","")
    prescription_medication_action=sec_output.get("Table_C_Analysis",{}).get("prescription_medication_action","")
    minor_procedure=sec_output.get("Table_C_Analysis",{}).get("minor_procedure","")
    table_c_evidence=sec_output.get("Table_C_Analysis",{}).get("evidence_sentance","")
    table_c_complexity=sec_output.get("Table_C_Analysis",{}).get("complexity_level","")
    explain=sec_output.get("explain","")
    tab_a_page=sec_output.get("Table_A_Analysis",{}).get("page","")
    tab_b_page=sec_output.get("Table_B_Analysis",{}).get("page","")
    tab_c_page=sec_output.get("Table_C_Analysis",{}).get("page","")
    final_level_sec=sec_output.get("final_level","")

# Table A calculations
    if acute_count==1 and chronic_count==1:
        table_a_complexity="moderate"
    elif acute_count>=2 and chronic_count>=2:
        table_a_complexity="moderate"
    elif acute_count==0 and chronic_count==1:
        table_a_complexity="low"
    elif acute_count==1 and chronic_count==0:
        table_a_complexity="low"
    elif table_a_acute_critical_condition.lower()=="yes":
        table_a_complexity="high"
    elif table_a_chronic_worsening.lower()=="yes":
        table_a_complexity="moderate"
    else:
        table_a_complexity="straightforward"

#table B calculations
    
    

    if isinstance(orders_count,str):
        orders_count=int(orders_count)
    if isinstance(imaging_count,str):
        imaging_count=int(imaging_count)

    Ordering=orders_count+imaging_count
    
    if isinstance(Ordering,int):
            Ordering=int(Ordering)
    if Ordering<=1:
        table_b_complexity="straightforward"
    elif Ordering==2:
        table_b_complexity="low"    
    elif Ordering>2:
        table_b_complexity="moderate"
    
#table C calculations
    if current_medication_action.lower()=="yes" and Otc_drug.lower()=="yes":
        table_c_complexity="low"
    elif occupational_therapy.lower()=="yes":
        table_c_complexity="low"
    elif physical_therapy.lower()=="yes":
        table_c_complexity="low"
    elif current_medication_action.lower()=="yes" and prescription_medication_action.lower()=="yes":
        table_c_complexity="moderate"
    elif current_medication_action.lower()=="yes" and prescription_medication_action.lower()=="no" and Otc_drug.lower()=="no":
        table_c_complexity="low"
    elif minor_procedure.lower()=="yes":
        table_c_complexity="moderate"
    else:
        table_c_complexity="straightforward"

    if isinstance(tab_a_page,str):
        try:
            tab_a_page=int(tab_a_page)
        except Exception:
            tab_a_page=None
    if isinstance(tab_b_page,str):
        try:
            tab_b_page=int(tab_b_page)
        except Exception:
            tab_b_page=None
    if isinstance(tab_c_page,str):
        try:
            tab_c_page=int(tab_c_page)
        except Exception:
            tab_c_page=None

    hard=False

    condition=[
        {
            "name":"Minimal risk of morbidity from additional diagnostic testing or treatment",
            "value":output.get("conditions")[0]["value"] if hard else None,
            "count":output.get("conditions")[0]["count"] if hard else None,
            "exactSentence":output.get("conditions")[0]["exactSentence"] if hard else "",
            "page":output.get("conditions")[0]["page"] if hard else None
        },
        {
            "name":"Low risk of morbidity from additional diagnostic testing or treatment",
            "value":output.get("conditions")[1]["value"] if hard else None,
            "count":output.get("conditions")[1]["count"] if hard else None,
            "exactSentence":output.get("conditions")[1]["exactSentence"] if hard else "",
            "page":output.get("conditions")[1]["page"] if hard else None
        },
        {
            "name":"Prescription drug management",
            "value":output.get("conditions")[2]["value"] if hard else current_medication_action,
            "count":output.get("conditions")[2]["count"] if hard else None,
            "exactSentence":output.get("conditions")[2]["exactSentence"] if hard else table_c_evidence,
            "page":output.get("conditions")[2]["page"] if hard else tab_c_page
        },
        {
            "name":"Decision regarding minor surgery with identified patient or procedure risk factors",
            "value":output.get("conditions")[3]["value"] if hard else None,
            "count":output.get("conditions")[3]["count"] if hard else None,
            "exactSentence":output.get("conditions")[3]["exactSentence"] if hard else "",
            "page":output.get("conditions")[3]["page"] if hard else None
        },
        {
            "name":"Decision regarding elective major surgery without identified patient or procedure risk factors",
            "value":output.get("conditions")[4]["value"] if hard else None,
            "count":output.get("conditions")[4]["count"] if hard else None,
            "exactSentence":output.get("conditions")[4]["exactSentence"] if hard else "",
            "page":output.get("conditions")[4]["page"] if hard else None
        },
        {
            "name":"Diagnosis or treatment significantly limited by social determinants of health",
            "value":output.get("conditions")[5]["value"] if hard else None,
            "count":output.get("conditions")[5]["count"] if hard else None,
            "exactSentence":output.get("conditions")[5]["exactSentence"] if hard else "",
            "page":output.get("conditions")[5]["page"] if hard else None
        },
        {
            "name":"Drug therapy requiring intensive monitoring for toxicity",
            "value":output.get("conditions")[6]["value"] if hard else None,
            "count":output.get("conditions")[6]["count"] if hard else None,
            "exactSentence":output.get("conditions")[6]["exactSentence"] if hard else "",
            "page":output.get("conditions")[6]["page"] if hard else None
        },
        {
            "name":"Decision regarding elective major surgery with identified patient or procedure risk factors",
            "value":output.get("conditions")[7]["value"] if hard else None,
            "count":output.get("conditions")[7]["count"] if hard else None,
            "exactSentence":output.get("conditions")[7]["exactSentence"] if hard else "",
            "page":output.get("conditions")[7]["page"] if hard else None
        },
        {
            "name":"Decision regarding emergency major surgery",
            "value":output.get("conditions")[8]["value"] if hard else None,
            "count":output.get("conditions")[8]["count"] if hard else None,
            "exactSentence":output.get("conditions")[8]["exactSentence"] if hard else "",
            "page":output.get("conditions")[8]["page"] if hard else None
        },
        {
            "name":"Decision regarding hospitalization or escalation of hospital-level care",
            "value":output.get("conditions")[9]["value"] if hard else None,
            "count":output.get("conditions")[9]["count"] if hard else None,
            "exactSentence":output.get("conditions")[9]["exactSentence"] if hard else "",
            "page":output.get("conditions")[9]["page"] if hard else None
        },
        {
            "name":"Decision not to resuscitate or to de-escalate care because of poor prognosis",
            "value":output.get("conditions")[10]["value"] if hard else None,
            "count":output.get("conditions")[10]["count"] if hard else None,
            "exactSentence":output.get("conditions")[10]["exactSentence"] if hard else "",
            "page":output.get("conditions")[10]["page"] if hard else None
        },
        {
            "name":"Parenteral controlled substances",
            "value":output.get("conditions")[11]["value"] if hard else None,
            "count":output.get("conditions")[11]["count"] if hard else None,
            "exactSentence":output.get("conditions")[11]["exactSentence"] if hard else "",
            "page":output.get("conditions")[11]["page"] if hard else None
        }
    ]
    risk=[
        {
            "name":"None or Minimal",
            "value":output.get("risk")[0]["value"] if hard else None,
            "count":output.get("risk")[0]["count"] if hard else None,
            "exactSentence":output.get("risk")[0]["exactSentence"] if hard else "",
            "page":output.get("risk")[0]["page"] if hard else None
        },
        {
            "name":"Review of prior external note(s) from each unique source",
            "value":output.get("risk")[1]["value"] if hard else None,
            "count":output.get("risk")[1]["count"] if hard else None,
            "exactSentence":output.get("risk")[1]["exactSentence"] if hard else "",
            "page":output.get("risk")[1]["page"] if hard else None
        },
        {
            "name":"Review of the result(s) of each unique test",
            "value":output.get("risk")[2]["value"] if hard else None,
            "count":output.get("risk")[2]["count"] if hard else None,
            "exactSentence":output.get("risk")[2]["exactSentence"] if hard else "",
            "page":output.get("risk")[2]["page"] if hard else None
        },
        {
            "name":"Ordering of each unique test",
            "value":output.get("risk")[3]["value"] if hard else "yes" if Ordering != 0 else None,
            "count":output.get("risk")[3]["count"] if hard else Ordering,
            "exactSentence":output.get("risk")[3]["exactSentence"] if hard else table_b_evidence,
            "page":output.get("risk")[3]["page"] if hard else tab_b_page
        },
        {
            "name":"Assessment requiring an independent historian(s)",
            "value":output.get("risk")[4]["value"] if hard else None,
            "count":output.get("risk")[4]["count"] if hard else None,
            "exactSentence":output.get("risk")[4]["exactSentence"] if hard else "",
            "page":output.get("risk")[4]["page"] if hard else None
        },
        {
            "name":"Independent interpretation of a test performed by another physician/other qualified health care professional (not separately reported)",
            "value":output.get("risk")[5]["value"] if hard else None,
            "count":output.get("risk")[5]["count"] if hard else None,
            "exactSentence":output.get("risk")[5]["exactSentence"] if hard else "",
            "page":output.get("risk")[5]["page"] if hard else None
        },
        {
            "name":"Discussion of management or test interpretation with external physician/other qualified health care professional/appropriate source (not separately reported)",
            "value":output.get("risk")[6]["value"] if hard else None,
            "count":output.get("risk")[6]["count"] if hard else None,
            "exactSentence":output.get("risk")[6]["exactSentence"] if hard else "",
            "page":output.get("risk")[6]["page"] if hard else None
        },

    ]
    problems=[
        {   
            "name":"self-limited or minor problem",
            "value":output.get("problems")[0]["value"] if hard else None,
            "count":output.get("problems")[0]["count"] if hard else None,
            "exactSentence":output.get("problems")[0]["exactSentence"] if hard else "",
            "page":output.get("problems")[0]["page"] if hard else None
        },
        {
            "name":"stable chronic illness",
            "value": output.get("problems")[1]["value"] if hard else "yes" if chronic_count != 0 else None,
            "count":output.get("problems")[1]["count"] if hard else chronic_count,
            "exactSentence":output.get("problems")[1]["exactSentence"] if hard else  table_a_evidence_chronic,
            "page":output.get("problems")[1]["page"] if hard else tab_a_page
        },
        {
            "name":"acute, uncomplicated illness or injury",
            "value":output.get("problems")[2]["value"] if hard else None,
            "count":output.get("problems")[2]["count"] if hard else None,
            "exactSentence":output.get("problems")[2]["exactSentence"] if hard else "",
            "page":output.get("problems")[2]["page"] if hard else None
        },
        {
            "name":"stable acute illness",
            "value":output.get("problems")[3]["value"] if hard else "yes" if acute_count != 0 else None ,
            "count":output.get("problems")[3]["count"] if hard else acute_count,
            "exactSentence":output.get("problems")[3]["exactSentence"] if hard else table_a_evidence_acute,
            "page":output.get("problems")[3]["page"] if hard else None
        },
        {
            "name":"acute, uncomplicated illness or injury requiring hospital inpatient or observation level of care",
            "value":output.get("problems")[4]["value"] if hard else None,
            "count":output.get("problems")[4]["count"] if hard else None,
            "exactSentence":output.get("problems")[4]["exactSentence"] if hard else "",
            "page":output.get("problems")[4]["page"] if hard else None
        },
        {
            "name":"chronic illnesses with exacerbation, progression, or side effects of treatment",
            "value":output.get("problems")[5]["value"] if hard else None,
            "count":output.get("problems")[5]["count"] if hard else None,
            "exactSentence":output.get("problems")[5]["exactSentence"] if hard else "",
            "page":output.get("problems")[5]["page"] if hard else None
        },
        {
            "name":"undiagnosed new problem with uncertain prognosis",
            "value":output.get("problems")[6]["value"] if hard else None,
            "count":output.get("problems")[6]["count"] if hard else None,
            "exactSentence":output.get("problems")[6]["exactSentence"] if hard else "",
            "page":output.get("problems")[6]["page"] if hard else None
        },
        {
            "name":"acute illness with systemic symptoms",
            "value":output.get("problems")[7]["value"] if hard else None,
            "count":output.get("problems")[7]["count"] if hard else None,
            "exactSentence":output.get("problems")[7]["exactSentence"] if hard else "",
            "page":output.get("problems")[7]["page"] if hard else None
        },
        {
            "name":"acute complicated injury",
            "value":output.get("problems")[8]["value"] if hard else None,
            "count":output.get("problems")[8]["count"] if hard else None,
            "exactSentence":output.get("problems")[8]["exactSentence"] if hard else "",
            "page":output.get("problems")[8]["page"] if hard else None
        },
        {
            "name":"chronic illnesses with severe exacerbation, progression, or side effects of treatment",
            "value":output.get("problems")[9]["value"] if hard else None,
            "count":output.get("problems")[9]["count"] if hard else None,
            "exactSentence":output.get("problems")[9]["exactSentence"] if hard else "",
            "page":output.get("problems")[9]["page"] if hard else None
        },
        {
            "name":"acute or chronic illness or injury that poses a threat to life or bodily function",
            "value":output.get("problems")[10]["value"] if hard else None,
            "count":output.get("problems")[10]["count"] if hard else None,
            "exactSentence":output.get("problems")[10]["exactSentence"] if hard else "",
            "page":output.get("problems")[10]["page"] if hard else None
        }
    ]
    final_level=output.get("finalLevel") if hard else final_level_sec
    cpt_code=""
    final_level=final_level.lower() if final_level else ""
    if final_level=="":
        final_level=None
    if final_level=="straightforward":
        cpt_code="99212" if output.get("patientType","").lower()=="established" else "99202"
    elif final_level=="low":
        cpt_code="99213" if output.get("patientType","").lower()=="established" else "99203"
    elif final_level=="moderate":
        cpt_code="99214" if output.get("patientType","").lower()=="established" else "99204"
    elif final_level=="high":
        cpt_code="99215" if output.get("patientType","").lower()=="established" else "99205"
    output={
        "problemsLevel": output.get("problemsLevel") if hard else table_a_complexity,
        "riskLevel": output.get("riskLevel") if hard else table_b_complexity,
        "conditionLevel": output.get("conditionLevel") if hard else table_c_complexity,
        "finalLevel": output.get("finalLevel") if hard else final_level,
        "patientType": output.get("patientType"),
        "modifiers": output.get("modifiers"),
        "cptCode": cpt_code,
        "conditions": condition,
        "risk": risk,
        "problems": problems

    }
    return output
async def output(text: str, trace_id: str) -> dict:
    raw_ai = await ai_call_qwen(text, mdm_prompt)
    raw_ai = await json_clean(raw_ai)
    #if isinstance(raw_ai, dict):
        #logger.info(f"MDM Validated AI output for trace_id: {trace_id}: {raw_ai}")
        #raw_ai = await validate_with_ai(text, raw_ai)

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
    logger.info(f"MDM preliminary final output for trace_id: {trace_id}: {final_output}")
    sec_call = await full_output(text, trace_id)

    if isinstance(sec_call, dict):
         final_output.update(sec_call)
    final_output = final_return(final_output, sec_call)
    logger.info(f"MDM full final output for trace_id: {trace_id}: {final_output}")
    return final_output

async def get_mdm(text, trace_id: str):
    result=await output(text, trace_id)
    print(result)
    logger.info(f"MDM result for trace_id: {trace_id}: {result}")
    return result
