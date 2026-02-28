import logging
import os
from pydantic import BaseModel
from dotenv import load_dotenv
from utils.ai import ai_call_demo
import json

load_dotenv()
DEMO_URL_BACKEND = os.getenv("DEMO_URL_BACKEND")
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("pii")


_model_pp = None

#def get_gliner_model():
#    global _model_pp
#    if _model_pp is None:
#        model_path = os.getenv("GLINER_MODEL_PATH", "./model/gliner-pii-large-v1.0")
#        _model_pp = GLiNER.from_pretrained(model_path,local_files_only=True)
#    return _model_pp

#label_pp = [
#    "patient name","email", "accountNumber", "MRN", "DOB","visit date",
#    "Gender", "SSN", "Financial Class", "insurance name", "age"
#]

#class Item(BaseModel):
#    text: str


#def safe_extract(result, label: str, patient_id: str = None):
#    pid_log = f"patient={patient_id} " if patient_id else ""
#    if result and isinstance(result, list) and len(result) > 0 and len(result[0]) > 0:
#        text = result[0][0].get("text", "")
#        logger.info(f"[PII-EXTRACT-SUCCESS] {pid_log}label={label} value={text}")
#        return text
#    logger.warning(f"[PII-EXTRACT-NOT-FOUND] {pid_log}label={label} Not found in second try")
#    return ""


#def financial_fix(output, text, patient_id: str = None):
#    pid_log = f"patient={patient_id} " if patient_id else ""
#    if "Financial Class" in output and output["Financial Class"]:
#        logger.info(f"[PII-FINANCIAL-FOUND] {pid_log}value={output['Financial Class'][0]}")
#        return output["Financial Class"][0]

#    match = re.findall(r'Financial Class:\s*(\w+)',text)
#    if match:
#        logger.info(f"[PII-FINANCIAL-REGEX] {pid_log}value={match[0].strip()}")
#      return match[0].strip()

#    logger.warning(f"[PII-FINANCIAL-NOT-FOUND] {pid_log}Not found, trying GLiNER second attempt")
#    model_pp = get_gliner_model()  # Lazy load
#    result = model_pp.run(text, labels=["Financial Class"], threshold=0.05)
#    logger.debug(f"[PII-FINANCIAL-DEBUG] {pid_log}result={result}")
#    if result:
#        return safe_extract(result, "Financial Class", patient_id)
#    logger.warning(f"[PII-FINANCIAL-FAIL] {pid_log}Not found by GLiNER in second try")
#    return ""

#def ssn_fix(output, patient_id: str = None):
#    pid_log = f"patient={patient_id} " if patient_id else ""
#    if "SSN" in output and output["SSN"]:
#        candidate = output["SSN"][0]
#        logger.info(f"[PII-SSN-CANDIDATE] {pid_log}candidate={candidate}")
#        if len(candidate) > 4:
#            logger.info(f"[PII-SSN-VALID] {pid_log}value={candidate}")
#            return candidate
#        logger.warning(f"[PII-SSN-INVALID] {pid_log}candidate too short, discarded")
#    return ""

#def dob_fix(output, patient_id: str = None):
#    pid_log = f"patient={patient_id} " if patient_id else ""
#    if "DOB" in output and output["DOB"]:
#        logger.info(f"[PII-DOB-FOUND] {pid_log}value={output['DOB'][0]}")
#        return output["DOB"][0] 
#    logger.warning(f"[PII-DOB-NOT-FOUND] {pid_log}No DOB found")
#    return ""

#def name_fix(output, text, patient_id: str = None):
#    pid_log = f"patient={patient_id} " if patient_id else ""
#    if "patient name" in output and output["patient name"]:
#        logger.info(f"[PII-NAME-FOUND] {pid_log}value={output['patient name'][0]}")
#        return output["patient name"][0]
#    logger.warning(f"[PII-NAME-NOT-FOUND] {pid_log}Not found in first try, trying GLiNER second attempt")
#    model_pp = get_gliner_model()  # Lazy load
#    result = model_pp.run(text, labels=["patient name"], threshold=0.05)
#    logger.debug(f"[PII-NAME-DEBUG] {pid_log}result={result}")
#    if result:
#        return safe_extract(result, "patient name", patient_id)
#    logger.warning(f"[PII-NAME-FAIL] {pid_log}Not found by GLiNER in second try")
#    return ""
#def date_of_service_fix(output, text, patient_id: str = None):
#    pid_log = f"patient={patient_id} " if patient_id else ""
#    if "Date of service" in output and output["Date of service"]:
#        logger.info(f"[PII-DATE-FOUND] {pid_log}type=Date of service value={output['Date of service'][0]}")
#        return output["Date of service"][0]
#    if "visit date" in output and output["visit date"]:
#        logger.info(f"[PII-DATE-FOUND] {pid_log}type=visit date value={output['visit date'][0]}")
#        return output["visit date"][0]
#    logger.warning(f"[PII-DATE-NOT-FOUND] {pid_log}Not found in first try, trying GLiNER second attempt")
#    model_pp = get_gliner_model()  # Lazy load
#    result = model_pp.run(text, labels=["Date of service","visit date"], threshold=0.05)
#    logger.debug(f"[PII-DATE-DEBUG] {pid_log}result={result}")
#    if result:
#        return safe_extract(result, "Date of service", patient_id)
#    logger.warning(f"[PII-DATE-FAIL] {pid_log}Not found by GLiNER in second try")
#    return ""

#prompt="""Your task is to extract ONLY the primary insurance company name from the provided patient demographic text.

#Business Rules:
#1. Find the substring "*****PRIMARY INSURANCE*****" (case-insensitive).
#2. Extract the text that immediately follows this header.
#3. The primary insurance company name is the FIRST alphabetical phrase (letters and spaces only) that appears after the header, before ANY of these markers:
#   - "POBOX"
#   - "P.O."
#   - any digit
#   - "Insurance"
#   - "Relationship"
#   - "INSURED PARTY"
#   - "*****SECONDARY INSURANCE*****"
#4. Ignore all secondary or additional insurance information.
#5. Strip out noise, numbers, punctuation, and non-letter characters unless part of the actual name.
#6. Return the result ONLY in this JSON format:
#   {"insurance_name": "<value>"}
#7. If you absolutely cannot identify a company name after the PRIMARY INSURANCE header, return:
#   {"insurance_name": ""}

#Example:
#Input: "*****PRIMARY INSURANCE*****VIRGINIA BLUE SHIELD POBOX27401..."
#Output: {"insurance_name": "VIRGINIA BLUE SHIELD"}


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
"""
def insurance_name_fix(text, patient_id: str = None):
    pid_log = f"patient={patient_id} " if patient_id else ""
    logger.debug(f"[PII-INSURANCE-START] {pid_log}Extracting insurance name")
    text = "primary insurance company name: " + text
    result = ai_call_demo(text, prompt)
    result = json_clean(result)
    logger.info(f"[PII-INSURANCE-RESULT] {pid_log}result={result}")
    if result and result.get("insurance_name"):
        logger.info(f"[PII-INSURANCE-FOUND] {pid_log}value={result['insurance_name']}")
        return result["insurance_name"]
    logger.warning(f"[PII-INSURANCE-NOT-FOUND] {pid_log}No insurance name found")
    return ""

def out_fix(output, text, patient_id: str):
    logger.info(f"[PII-OUT-FIX-START] patient={patient_id} Building structured output")
    new_output = {
        "name": name_fix(output, text, patient_id),
        "Date of service": date_of_service_fix(output, text, patient_id),
        "date of birth": dob_fix(output, patient_id),
        "email": output["email"][0] if "email" in output else "",
        "accountNumber": output["accountNumber"][0] if "accountNumber" in output else "",
        "MRN": output["MRN"][0] if "MRN" in output else "",
        "Insurance name": insurance_name_fix(text, patient_id),
        "SSN": ssn_fix(output, patient_id),
        "age": output["age"][0] if "age" in output else "",
        "Financial Class": financial_fix(output, text, patient_id),
        "gender": output["Gender"][0] if "Gender" in output else ""
    }
    logger.info(f"[PII-OUT-FIX-SUCCESS] patient={patient_id} Structured output completed")
    logger.debug(f"[PII-OUT-FIX-DEBUG] patient={patient_id} output={new_output}")
    return new_output

def pii_detection(text: str, patient_id: str):
    logger.info(f"[PII-DETECTION-START] patient={patient_id} text_length={len(text)} Running PII detection")
    model_pp = get_gliner_model()  # Lazy load
    result = model_pp.run(text, labels=label_pp, threshold=0.3)
    logger.info(f"[PII-DETECTION-RESULT] patient={patient_id} GLiNER detection completed")
    logger.debug(f"[PII-DETECTION-DEBUG] patient={patient_id} result={result}")
    
    if result is None:
        logger.warning(f"[PII-DETECTION-ERROR] patient={patient_id} No text provided")
        return {}
    
    output = {}
    for i in result:
        for j in i:
            label = j["label"]  
            entity = j["text"]
            if label not in output:
                output[label] = [entity]
            else:
                output[label].append(entity)
            logger.debug(f"[PII-DETECTION-ENTITY] patient={patient_id} label={label} entity={entity}")
    
    logger.info(f"[PII-DETECTION-KEYS] patient={patient_id} detected_keys={list(output.keys())}")
    return out_fix(output, text, patient_id)

import requests
from pypdf import PdfReader
import io
def download_blob_text(url: str, patient_id: str = None) -> str:
    pid_log = f"patient={patient_id} " if patient_id else ""
    logger.info(f"[PII-DOWNLOAD-START] {pid_log}url={url} Downloading blob")
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        reader = PdfReader(io.BytesIO(resp.content))
        text = "".join(page.extract_text() or "" for page in reader.pages)
        logger.info(f"[PII-DOWNLOAD-SUCCESS] {pid_log}url={url} text_length={len(text)}")
        return text
    except Exception as e:
        logger.error(f"[PII-DOWNLOAD-ERROR] {pid_log}url={url} error={e}")
        raise

def pii_detection_demo(blob_url: str, patient_id: str, traceDto: dict, returnHeaders: dict):
    logger.info(f"[PII-DEMO-START] patient={patient_id} url={blob_url} Starting PII detection demo")
    
    text = download_blob_text(blob_url, patient_id)
    
    text = text.lower()
    logger.info(f"[PII-DEMO-TEXT] patient={patient_id} text_length={len(text)} text_preview={text[:100]}")

    try:
        model_pp = get_gliner_model()  # Lazy load
        logger.info(f"[PII-DEMO-MODEL] patient={patient_id} Model loaded successfully")
        result = model_pp.run(text, labels=label_pp, threshold=0.3)
        logger.info(f"[PII-DEMO-DETECTION] patient={patient_id} GLiNER detection completed")
    except Exception as e:
        logger.error(f"[PII-DEMO-ERROR] patient={patient_id} Error in model_pp.run: {e}")
        return {"status": "error", "message": str(e)}
    
    logger.debug(f"[PII-DEMO-RESULT] patient={patient_id} result={result}")

    if result is None:
        logger.warning(f"[PII-DEMO-NO-TEXT] patient={patient_id} No text provided")
        return {"status": "no_text"}

    output = {}
    for batch in result:
        for item in batch:
            label = item["label"]
            entity = item["text"]
            output.setdefault(label, []).append(entity)
            logger.debug(f"[PII-DEMO-ENTITY] patient={patient_id} label={label} entity={entity}")

    logger.info(f"[PII-DEMO-KEYS] patient={patient_id} detected_keys={list(output.keys())}")

    result_structured = out_fix(output, text, patient_id)
    payload = {
        "patientId": patient_id,
        "patientResponseDTO": result_structured,
        "traceDto": traceDto,
    }

    logger.info(f"[PII-DEMO-PAYLOAD] patient={patient_id} payload={payload}")
    logger.info(f"[PII-DEMO-BACKEND-REQUEST] patient={patient_id} url={DEMO_URL_BACKEND} Sending to backend")

    try:
        response = requests.post(DEMO_URL_BACKEND, json=payload, headers=returnHeaders, timeout=10)
        logger.info(f"[PII-DEMO-BACKEND-SUCCESS] patient={patient_id} status={response.status_code} Backend responded")
        return {"status": response.status_code}
    except requests.exceptions.RequestException as e:
        logger.error(f"[PII-DEMO-BACKEND-ERROR] patient={patient_id} url={DEMO_URL_BACKEND} Failed to send: {e}")
        return {"status": "error", "message": str(e)}
"""
#---------------NEW----------------------#
prompt_demo_extraction = """
Extract the specified patient details from the provided clinical text or medical chart.
Populate JSON & Explain Reasoning
For each extracted condition, populate the JSON structure with a clear explanation.
 "patientType": "" # "Established" # or "New" If CPT explicitly contains EST PAT codes (e.g., 99213, 99214, OFFICE VISIT EST PAT) → patientType = "ESTABLISHED" If CPT explicitly contains NEW PAT codes(e.g., 99202, 99203, OFFICE VISIT NEW PAT) → patientType = "NEW" 
 If NO CPT / PROCEDURE section exists → patientType = "" 
 if synonms of eg: Outpatient also consider as Established 
 important note where NEW and Established only allowed in this!
Fields to Extract:
- name
- dateOfService
- ateOfBirth
- email
- accountNumber
- mrn
- insuranceName
- ssn
- age
- financialClass
- gender
- patientType

Extraction and Formatting Rules:

- Extract the information exactly as it appears in the text for most fields.
- Special Date Rule: Format the dateOfService and dateOfBirth fields strictly as MM/DD/YYYY. If a date is found in a different format (e.g., DD-MM-YYYY, YYYY/MM/DD, "January 15, 2024"), convert it to MM/DD/YYYY.
- If a field is not found in the text, assign an empty string "".
- Return ONLY a valid JSON object with the keys listed above.
Do not include any explanations, notes, or other text.
Example Output Format:
{
  "name": "John Doe",
  "dateOfService": "09/15/2025",
  "dateOfBirth": "03/22/1985",
  "email": "john.doe@example.com",
  "accountNumber": "ACC123456",
  "mrn": "MRN789456",
  "insuranceName": "Aetna Health Insurance",
  "ssn": "123-45-6789",
  "age": "40",
  "financialClass": "Commercial",
  "gender": "Male",
  "patientType": "NEW/Established"
}
"""

async def pii_ai_demo(text, patient_id):
    logger.info(f"[PII-DEMO-START] patient={patient_id}")

    if not text:
        logger.warning(f"[PII-DEMO-EMPTY-TEXT] patient={patient_id}")
        return {
            "name": "",
            "dateOfService": "",
            "dateOfBirth": "",
            "email": "",
            "accountNumber": "",
            "mrn": "",
            "insuranceName": "",
            "ssn": "",
            "age": "",
            "financialClass": "",
            "gender": "",
            "patientType": ""
        }

    logger.info(
        f"[PII-DEMO-TEXT] patient={patient_id} "
        f"text_length={len(text)} text_preview={text[:100]}"
    )

    ai_response = ai_call_demo(text, prompt_demo_extraction)

    result = json_clean(ai_response)

    # Ensure all required keys exist
    final_result = {
        "name": result.get("name", ""),
        "dateOfService": result.get("dateOfService", ""),
        "dateOfBirth": result.get("dateOfBirth", ""),
        "email": result.get("email", ""),
        "accountNumber": result.get("accountNumber", ""),
        "mrn": result.get("mrn", ""),
        "insuranceName": result.get("insuranceName", ""),
        "ssn": result.get("ssn", ""),
        "age": result.get("age", ""),
        "financialClass": result.get("financialClass", ""),
        "gender": result.get("gender", ""),
        "patientType": result.get("patientType", "").upper()
    }

    logger.info(f"[PII-DEMO-END] patient={patient_id} final_result {final_result}")
    return final_result
