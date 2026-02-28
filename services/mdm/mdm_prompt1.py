mdm_prompt = """

# TASK INSTRUCTIONS

Analyze the input document. For each section below (CONDITIONS, RISK, PROBLEMS, PATIENT_TYPE), follow ALL their rules.
- Return your output in **valid JSON only**.
- Do not add any extra text, explanations, or headings.
- The JSON format must be:
{
"condition": {...},
"risk": {...},
"problems": {...},
"patientType": {...},
"conditon_hyperlink":{...},
"risk_hyperlink":{...},
"problems_hyperlink":{...},

} 

# SECTIONS
## CONDITIONS

STRICT RULE:

Provide your responses in JSON format, where the keys are reference IDs (in camelCase) and the values are either "yes" or "no".
                     
Questions to Answer (Based on Uploaded Files):
                     
1. MIN_RISK – Does the patient’s current condition involve only a minimal risk of morbidity
   or complications if additional diagnostic testing or treatment is performed?
   (e.g., routine labs, simple imaging, or very low-risk interventions).
      
2. LOW_RISK – Does the patient’s current condition involve only a low risk of morbidity
   or complications from additional diagnostic testing or treatment?
   (e.g., minor skin procedures, basic prescriptions without significant monitoring needs).
      
3. RX_MGMT – Did the provider initiate, adjust, or discontinue prescription drug therapy
   as part of the patient’s care? (This includes medication review, starting new drugs,
   dosage changes, or considering interactions).
      
4. MIN_SURG_RISK – Was a decision made regarding minor surgery
   (e.g., mole removal, joint injection) with patient-specific or procedure-related
   risk factors that required clinical judgment?
      
5. MAJ_SURG_NO_RISK – Was a decision made regarding elective major surgery
   (e.g., joint replacement, hernia repair) without any identified patient-specific
   or procedural risk factors?
      
6. SDOH_LIMIT – Was the patient’s diagnosis or treatment plan significantly limited
   or complicated by social determinants of health
   (e.g., financial hardship, lack of transportation, limited health literacy, language barriers)?

7. TOX_MONITOR – Was the patient considered for drug therapy requiring intensive monitoring
   for toxicity (e.g., chemotherapy, anticoagulants, immunosuppressants) where regular labs
   or close observation are required?

8. MAJ_SURG_WITH_RISK – Was a decision made regarding elective major surgery with identified
   risk factors related to the patient (e.g., diabetes, heart disease) or the procedure
   (e.g., high blood loss risk)?

9. EMERG_SURG – Was a decision made regarding emergency major surgery where urgent
   surgical intervention was necessary to address a life-threatening or time-sensitive condition?
10. HOSP_ESCALATE – Was there a decision to hospitalize the patient or escalate care
   to a hospital-level setting due to the severity of illness, complications, or worsening prognosis?
11. DNR – Was a decision made regarding not resuscitating the patient
   (Do Not Resuscitate order) or to de-escalate aggressive care due to poor prognosis
   or patient/family wishes?
12. IV_CONTROLLED – Were parenteral (IV, IM, or other non-oral routes) controlled substances
   administered or prescribed during this encounter?
   (e.g., IV morphine, fentanyl, ketamine).

RULES:
- Hyperlink does NOT decide logic
- "answer" MUST mirror conditions value
- exact_sentence must be ONE keyword OR short phrase copied verbatim
- If no evidence exists, leave page null and sentence empty

Expected JSON Format,strictly follow json format:
"conditions":{
   "minRisk": "yes" or "no",
   "lowRisk": "yes" or "no",
   "rxMgmt": "yes" or "no",
   "minSurgRisk": "yes" or "no",
   "majSurgNoRisk": "yes" or "no",
   "sdohLimit": "yes" or "no",
   "toxMonitor": "yes" or "no",
   "majSurgWithRisk": "yes" or "no",
   "emergSurg": "yes" or "no",
   "hospEscalate": "yes" or "no",
   "dnr": "yes" or "no",
   "ivControlled": "yes" or "no"
}

Rules for conditions_hyperlink:

1. Answer Requirement:
   -  Every answer must be either true or false.
   -  The answer must be supported by compulsory evidence from the content.

2. Evidence Sentence:
   -  "exact_sentence" must be copied word-for-word from the user’s input OCR text.
   -  only Important one word should be present in the exact_sentence
   -  If no exact match exists in the input OCR text, "exact_sentence" must be an empty string: "".

3. Page Number:
   -  Include the exact page number where the supporting sentence is found.
   -  This must correspond precisely to the location of the sentence in the OCR text.

4. Missing Evidence:
   -  If no exact sentence or page number can be found in the OCR text, both should be returned as empty strings: "".

"conditions_hyperlink": {
   "minRisk": {"page": null, "exact_sentence": "","answer":  "true" or "false"},
   "lowRisk": {"page": null, "exact_sentence": "","answer": "true" or "false"},
   "rxMgmt": {"page": null, "exact_sentence": "","answer": "true" or "false"},
   "minSurgRisk": {"page": null, "exact_sentence": "","answer": "true" or "false"},
   "majSurgNoRisk": {"page": null, "exact_sentence": "","answer": "true" or "false"},
   "sdohLimit": {"page": null, "exact_sentence": "","answer": "true" or "false"},
   "toxMonitor": {"page": null, "exact_sentence": "","answer": "true" or "false"},
   "majSurgWithRisk": {"page": null, "exact_sentence": "","answer": "true" or "false"},
   "emergSurg": {"page": null, "exact_sentence": "","answer": "true" or "false"},
   "hospEscalate": {"page": null, "exact_sentence": "","answer": "true" or "false"},
   "dnr": {"page": null, "exact_sentence": "","answer": "true" or "false"},
   "ivControlled": {"page": null, "exact_sentence": "","answer": "true" or "false"}
}


## RISK
You are given a list of yes/no questions based on medical documentation activities.

Please analyze the uploaded file(s) and answer each question with "yes" or "no" based on the documentation and a hyperLink object for each respective question.
If evidence is found for a specific scenario in the file, answer “yes”, if no evidence is found answer “no”.
The hyperlink object should include the page number and the exact string from the content that supports the answer. If the answer is "yes," provide the page number where the supporting evidence is found and the exact text from that page that supports the answer. If the answer is "no," make the hyperlink object null.

STRICT RULE:

Provide your answers in JSON format, where the keys are reference IDs and the values are either "yes", "no", or a number (if counting is required).

Questions to Answer (Based on Uploaded Files):

1. NM – Does the documentation show that no data or only very limited data was reviewed or analyzed?
   For example, no labs, imaging, or outside notes were reviewed, only simple chart information referenced.

2. RENOTE – Does the documentation show that the provider reviewed notes from an external source
   (another physician, facility, or healthcare professional)?
   If yes, how many unique sources of notes were reviewed?
   Example: review of a cardiology consult note and a physical therapy note = 2 unique sources.

3. RTEST – Does the documentation show that the provider reviewed results of unique diagnostic tests?
   If yes, how many different test results were reviewed?
   Example: reviewing a CBC result and an MRI result = 2 unique tests.

4. OTEST – Does the documentation indicate that the provider ordered any new unique diagnostic tests? provide yes or no
   Example: ordering a chest X-ray, an EKG, or lab tests.
   Each test type is counted once, repeat orders of the same test are not counted multiple times.

5. IHIST – Was an independent historian (such as a parent, guardian, caregiver, or another individual)
   required to provide history because the patient could not give an adequate history?
   Example: a child’s parent provides the medical history, or a spouse provides history for a patient with dementia.

6. IINTERP – Did the provider perform an independent interpretation of a test that was ordered
   and documented by another physician or qualified healthcare professional, and not separately reported?
   Example: the provider reviews and interprets a chest X-ray performed in the emergency room
   and documents their own interpretation.

7. DMEXT – Does the documentation show that the provider had a direct discussion with an external physician,
   qualified healthcare professional, or appropriate healthcare source about patient management or test interpretation?
   Example: discYou are given a list of yes/no questions based on medical documentation activities.

RULES:
- Hyperlink does NOT decide logic
- "answer" MUST mirror conditions value
- exact_sentence must be ONE keyword OR short phrase copied verbatim
- If no evidence exists, leave page null and sentence empty


Expected JSON Format, strictly only respond with json:

{
"NM": "yes" or "no",
"RENOTE": 1,
"RTEST": 0,
"OTEST": "yes" or "no",
"IHIST": "yes" or "no",
"IINTERP": "yes" or "no",
"DMEXT": "yes" or "no"
}

1. Answer Requirement:
   -  Every answer must be either true or false or number or 0.
   -  The answer must be supported by compulsory evidence from the content.

2. Evidence Sentence:
   -  "exact_sentence"` must be copied word-for-word from the user’s input OCR text.
   -  only Important one word should be present in the exact_sentence
   -  If no exact match exists in the input OCR text, "exact_sentence" must be an empty string: "".

3. Page Number:
   -  Include the exact page number where the supporting sentence is found.
   -  This must correspond precisely to the location of the sentence in the OCR text.

4. Missing Evidence:
   -  If no exact sentence or page number can be found in the OCR text, both should be returned as empty strings: "".


"risk_hyperlink": {
   "NM": {"page": null, "exact_sentence": "","answer": true or false},
   "RENOTE": {"page": null, "exact_sentence": "","answer": 1},
   "RTEST": {"page": null, "exact_sentence": "","answer": 0},
   "OTEST": {"page": null, "exact_sentence": "","answer": true or false},
   "IHIST": {"page": null, "exact_sentence": "","answer": true or false},
   "IINTERP": {"page": null, "exact_sentence": "","answer": true or false},
   "DMEXT": {"page": null, "exact_sentence": "","answer": true or false}
}

## PROBLEMS
After analyzing the uploaded file, provide answers for each scenario.   
If no information is available for a particular question, respond with 0.

You are given a list of medical scenarios. For each scenario,
rate the severity or complexity on a scale from 0 (least severe) to 10 (most severe).


STRICT RULE:
For the exact string , the number of characters strictly should not exceed 15 characters.

Provide your answers in JSON format, using the reference ID as the key
and the rating (integer 0–10) as the value.

Reference IDs and Scenarios:

SLM: How many self-limited or minor problems are being addressed
   (e.g., colds, insect bites, simple rashes)?

SCI: How many stable chronic illnesses are being addressed
   (e.g., controlled hypertension, diabetes, or asthma without change in management)?

AUI: How many acute, uncomplicated illnesses or injuries are being addressed
   (e.g., urinary tract infection, sprain, superficial wound)?

SAI: How many stable acute illnesses are being addressed
   (e.g., acute otitis media, mild gastroenteritis, acute sinusitis not worsening)?

AUIO: How many acute, uncomplicated illnesses or injuries requiring inpatient or observation-level care
      (e.g., dehydration requiring IV fluids, asthma attack requiring observation, pneumonia requiring admission)?

CIE: How many chronic illnesses with exacerbation, progression, or side effects of treatment are being addressed
   (e.g., worsening COPD, uncontrolled diabetes, or medication side effects requiring adjustment)?

UNP: How many undiagnosed new problems with uncertain prognosis are being addressed
   (e.g., new lump, chest pain, neurological symptoms with unclear outcome)?

AIS: How many acute illnesses with systemic symptoms are being addressed
   (e.g., pyelonephritis, sepsis, influenza with dehydration, pneumonia with fever and malaise)?

ACI: How many acute complicated injuries are being addressed
   (e.g., head trauma, displaced fracture, injury with risk of functional impairment)?

CISE: How many chronic illnesses with severe exacerbation, progression,
      or side effects of treatment are being addressed
      (e.g., severe heart failure exacerbation, rapidly progressing cancer, worsening renal failure requiring dialysis)?

TLF: How many acute or chronic illnesses or injuries that pose a threat to life or bodily function
   (e.g., myocardial infarction, pulmonary embolism, stroke, severe respiratory distress, trauma with hemorrhage)?

Expected JSON Format:

Expected JSON Format,strictly follow json format:

{
   "SLM": 0,
   "SCI": 0,
   "AUI": 0,
   "SAI": 0,
   "AUIO": 0,
   "CIE": 0,
   "UNP": 0,
   "AIS": 0,
   "ACI": 0,
   "CISE": 0,
   "TLF": 0
   }

Rules for problems_hyperlink:
RULES:
- Hyperlink does NOT decide logic
- "answer" MUST mirror conditions value
- exact_sentence must be ONE keyword OR short phrase copied verbatim
- If no evidence exists, leave page null and sentence empty

1. Answer Requirement:
   -  Every answer must be either number or.
   -  The answer must be supported by compulsory evidence from the content.

2.Evidence Sentence:
   -  "exact_sentence" must be copied word-for-word from the user’s input OCR text.
   -  only Important one word should be present in the exact_sentence
   -  If no exact match exists in the input OCR text, "exact_sentence" must be an empty string: "".

3. Page Number:
   -  Include the exact page number where the supporting sentence is found.
   -  This must correspond precisely to the location of the sentence in the OCR text.

4. Missing Evidence:
   -  If no exact sentence or page number can be found in the OCR text, both should be returned as empty strings "".

   Without exact sentace no answer should present
 
"problems_hyperlink": {
   "SLM": {"page": null, "exact_sentence": "","answer": 0},
   "SCI": {"page": null, "exact_sentence": "","answer": 0},
   "AUI": {"page": null, "exact_sentence": "","answer": 0},
   "SAI": {"page": null, "exact_sentence": "","answer": 0},
   "AUIO": {"page": null, "exact_sentence": "","answer": 0},
   "CIE": {"page": null, "exact_sentence": "","answer": 0},
   "UNP": {"page": null, "exact_sentence": "","answer": 0},
   "AIS": {"page": null, "exact_sentence": "","answer": 0},
   "ACI": {"page": null, "exact_sentence": "","answer": 0},
   "CISE": {"page": null, "exact_sentence": "","answer": 0},
   "TLF": {"page": null, "exact_sentence": "","answer": 0}
}
## PATIENT_TYPE
You are an experienced Urgent Care coder.
Task:
Extract the patient type from the provided content and return "new" if patient is a new patient or else return "established".

# FINAL INSTRUCTION—IMPORTANT!
Return a SINGLE JSON object using these exact top-level keys:
check the patient chart if it patient chart means proced other wise make make it full empty string if int means 0 patient type also empty
{
"conditions": {...},
"risk": {...},
"problems": {...},
"patientType": "new" or "established" 
"conditions_hyperlink":{...},
"risk_hyperlink":{...},
"problems_hyperlink":{...},
}

Return nothing but this JSON. Fill all four keys, even if empty/zero/no.

"""