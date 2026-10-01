"""Streamlit dashboard served from the EC2 instance, backed by Athena.

Every query aggregates in Athena (only the referenced Parquet columns are
scanned) and results are cached for an hour, so page views do not each
trigger new billed queries.

Environment variables (set by the systemd unit from Terraform):
    ATHENA_DATABASE, ATHENA_TABLE, ATHENA_WORKGROUP, AWS_REGION
"""

from __future__ import annotations

import os

import boto3
import pandas as pd
import streamlit as st

from healthcare_pipeline.athena import run_query

DATABASE = os.environ["ATHENA_DATABASE"]
TABLE = os.environ["ATHENA_TABLE"]
WORKGROUP = os.environ["ATHENA_WORKGROUP"]
REGION = os.environ.get("AWS_REGION", "us-east-1")
CACHE_SECONDS = 3600


@st.cache_resource
def athena_client():
    return boto3.client("athena", region_name=REGION)


@st.cache_data(ttl=CACHE_SECONDS, show_spinner="Querying Athena...")
def query(sql: str) -> pd.DataFrame:
    return run_query(athena_client(), sql, database=DATABASE, workgroup=WORKGROUP)


def main() -> None:
    st.set_page_config(page_title="Patient summary", layout="wide")
    st.title("Patient summary")
    st.caption(f"Source: `{DATABASE}.{TABLE}` via Athena · cached for {CACHE_SECONDS // 60} min")

    kpis = query(
        f"""
        SELECT count(*) AS patients,
               round(avg(age_years), 1) AS avg_age,
               round(avg(encounter_count), 1) AS avg_encounters,
               round(sum(total_charges), 0) AS total_charges
        FROM {TABLE}
        """
    ).iloc[0]
    cols = st.columns(4)
    cols[0].metric("Patients", f"{int(kpis['patients']):,}")
    cols[1].metric("Average age", kpis["avg_age"] or "—")
    cols[2].metric("Avg encounters / patient", kpis["avg_encounters"] or "—")
    cols[3].metric("Total charges", f"${float(kpis['total_charges'] or 0):,.0f}")

    left, right = st.columns(2)
    with left:
        st.subheader("Patients by payer type")
        payers = query(
            f"""
            SELECT coalesce(payer_type, 'Unknown') AS payer_type, count(*) AS patients
            FROM {TABLE}
            GROUP BY 1
            ORDER BY 2 DESC
            """
        )
        payers["patients"] = payers["patients"].astype(int)
        st.bar_chart(payers, x="payer_type", y="patients", horizontal=True)
        st.dataframe(payers, hide_index=True, use_container_width=True)
    with right:
        st.subheader("Patients by age band")
        ages = query(
            f"""
            SELECT CASE
                     WHEN age_years IS NULL THEN 'Unknown'
                     WHEN age_years < 18 THEN '0-17'
                     WHEN age_years < 35 THEN '18-34'
                     WHEN age_years < 50 THEN '35-49'
                     WHEN age_years < 65 THEN '50-64'
                     ELSE '65+'
                   END AS age_band,
                   count(*) AS patients
            FROM {TABLE}
            GROUP BY 1
            ORDER BY 1
            """
        )
        ages["patients"] = ages["patients"].astype(int)
        st.bar_chart(ages, x="age_band", y="patients")
        st.dataframe(ages, hide_index=True, use_container_width=True)

    if st.button("Refresh data"):
        query.clear()
        st.rerun()


main()
