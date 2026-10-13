"""Synthetic CSVs matching the example pipeline_config.json. No real PHI."""

PATIENTS_CSV = b"""Patient ID,Birth Date,Sex,ZIP3
P001,1980-06-15,F,021
P002, 2010-01-01 ,M,100
P003,not-a-date,F,606
,1975-03-03,M,940
P001,1980-06-15,F,021
"""

ENCOUNTERS_CSV = b"""patient_id,encounter_count,last_encounter_date,total_charges
P001,4,2026-09-01,1000.50
P002,0,,0
P003,2.5,2026-08-15,300
"""

INSURANCE_CSV = b"""patient_id,payer_type,plan_start_date
P001,Commercial,2024-01-01
P002,Medicaid,2023-07-01
"""

FILES = {
    "patients.csv": PATIENTS_CSV,
    "encounters_summary.csv": ENCOUNTERS_CSV,
    "insurance.csv": INSURANCE_CSV,
}
