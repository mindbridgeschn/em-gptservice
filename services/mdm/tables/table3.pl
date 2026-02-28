
risk_level(minimal_risk_of_morbidity, straightforward).
risk_level(low_risk_of_morbidity, low).
risk_level(prescription_drug_management, moderate).
risk_level(minor_surgery_with_risk_factors, moderate).
risk_level(elective_major_surgery_without_risk_factors, moderate).
risk_level(sdh_limiting_diagnosis_or_treatment, moderate).
risk_level(drug_therapy_intensive_monitoring, high).
risk_level(elective_major_surgery_with_risk_factors, high).
risk_level(emergency_major_surgery, high).
risk_level(hospitalization_or_escalation, high).
risk_level(do_not_resuscitate_due_to_poor_prognosis, high).
risk_level(parenteral_controlled_substances, high).


risk_rank(straightforward, 1).
risk_rank(low, 2).
risk_rank(moderate, 3).
risk_rank(high, 4).


max_risk([], straightforward).  % base case
max_risk([H|T], MaxRisk) :-
    risk_level(H, RiskH),
    max_risk(T, RiskT),
    risk_rank(RiskH, RankH),
    risk_rank(RiskT, RankT),
    ( RankH >= RankT ->
        MaxRisk = RiskH
    ;
        MaxRisk = RiskT
    ).
