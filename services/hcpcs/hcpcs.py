import json
from typing import List, Optional   
from pydantic import BaseModel
import pandas as pd
from difflib import SequenceMatcher
from utils.ai import ai_call
from services.hcpcs.hcpcs_prompt import prompt
import asyncio
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
#======HCPCS data====================
hcpcs_data = [
    [1, "J7620", "Albuterol, up to 2.5 mg and ipratropium bromide, up to 0.5 mg, FDA-approved final product, non-compounded, administered through DME", 2.5],
    [2, "J7611", "Albuterol, inhalation solution, FDA-approved final product, non-compounded, administered through DME, concentrated form, 1 mg", 1],
    [3, "J7030", "Infusion, normal saline solution , 1000 cc", 1000],
    [4, "J2405", "Injection, ondansetron hydrochloride, per 1 mg", 1],
    [5, "J1885", "Injection, ketorolac tromethamine, per 15 mg", 15],
    [6, "J0696", "Injection, ceftriaxone sodium, per 250 mg", 250],
    [7, "J1100", "Injection, dexamethasone sodium phosphate, 1 mg", 1],
    [8, "J2360", "Injection, orphenadrine citrate, up to 60 mg", 60],
    [9, "J1200", "Injection, diphenhydramine HCl, up to 50 mg", 50],
    [10, "J2405", "Injection, ondansetron hydrochloride, per 1 mg", 1],
    [11, "J7030", "Infusion, normal saline solution , 1000 cc", 1000],
    [12, "J3301", "Injection, triamcinolone acetonide, not otherwise specified, 10 mg", 10],
    [13, "J2550", "Injection, promethazine HCl, up to 50 mg", 50],
]
hcpcs_df = pd.DataFrame(hcpcs_data, columns=["SNO", "CODE", "DESCRIPTION", "BASE_UNIT_MG"])

class DrugCodeResult(BaseModel):
    drug_name: str
    drug_code: Optional[str] = None
    evidence_sentence: Optional[str] = None
    page_number: Optional[int] = None

class ApiResponse(BaseModel):
    drugs_extracted: List[DrugCodeResult]

class AiExtractedDrug(BaseModel):
    drug_name: str
    dose_mg: Optional[float] = None
    evidence_sentence: Optional[str] = None 
    page_number: Optional[int] = None

async def string_similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()

async def token_match(drug_name: str, description: str) -> bool:
    tokens = [t.lower() for t in drug_name.replace("-", " ").split()]
    desc = description.lower()
    return all(t in desc for t in tokens)

async def find_hcpcs_code(drug_name: str, dose_mg: Optional[float], trace_id: str) -> Optional[str]:
    logger.info(f"HCPCS find_hcpcs_code for trace_id: {trace_id}: {drug_name} {dose_mg}")
    best_row = None
    best_score = 0.0
    for row in hcpcs_df.itertuples():
        score = token_match(drug_name, row.DESCRIPTION)
        if score > best_score:
            best_score = score
            best_row = row
    if best_row is None:
        return None
    code = best_row["CODE"]
    base = best_row["BASE_UNIT_MG"]
    if dose_mg is not None and base:
        try:
            d = float(dose_mg)
            b = float(base)
            if b == 0:
                return code
            mult = round(d / b)
            return f"{code}X{mult}" if mult > 1 else code
        except (ValueError, TypeError):
            return code
    return code

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


async def get_hcpcs(request_text: str, trace_id: str):
    logger.info(f"HCPCS get_hcpcs for trace_id: {trace_id}")
    ai_output = await ai_call(request_text, prompt)   
    cleaned = await json_clean(ai_output)
    logger.info(f"HCPCS cleaned for trace_id: {trace_id}: {cleaned}")
    logger.info(f"HCPCS get_hcs output for trace_id: {trace_id}: {cleaned}")
    return cleaned