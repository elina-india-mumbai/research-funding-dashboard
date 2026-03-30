import streamlit as st
import requests
import plotly.express as px
import pandas as pd

st.set_page_config(page_title="Research Funding Dashboard", layout="wide")
st.title("Federal Research Funding to Higher Education (FY2021–2026)")

BASE = "https://api.usaspending.gov/api/v2"

AGENCIES = {
    "DoD": "Department of Defense",
    "DOE": "Department of Energy",
    "HHS": "Department of Health and Human Services",
    "DHS": "Department of Homeland Security",
    "NSF": "National Science Foundation"
}

# Higher education recipient types recognized by USAspending API
HE_RECIPIENT_TYPES = [
    "public_institution_of_higher_education",
    "private_institution_of_higher_education",
    "minority_serving_institution_of_higher_education",
]

# ---------- Helpers ----------
def agency_filter(name):
    return [{"type": "awarding", "tier": "toptier", "name": name}]

def fy_dates(fy):
    return {"start_date": f"{fy - 1}-10-01", "end_date": f"{fy}-09-30"}

def base_filters(agency_name, fy):
    """Common filter block used across all API calls."""
    dates = fy_dates(fy)
    return {
        "time_period": [dates],
        "agencies": agency_filter(agency_name),
        "recipient_type_names": HE_RECIPIENT_TYPES,
    }

@st.cache_data(ttl=3600)
def get_state_spending(agency_name, fy):
    payload = {
        "scope": "place_of_performance",
        "geo_layer": "state",
        "filters": base_filters(agency_name, fy)
    }
    r = requests.post(f"{BASE}/search/spending_by_geography/", json=payload)
    r.raise_for_status()
    return pd.DataFrame(r.json().get("results", []))

@st.cache_data(ttl=3600)
def get_top_recipients(agency_name, fy):
    payload = {
        "category": "recipient",
        "filters": base_filters(agency_name, fy),
        "limit": 10
    }
    r = requests.post(f"{BASE}/search/spending_by_category/recipient", json=payload)
    r.raise_for_status()
    return pd.DataFrame(r.json().get("results", []))

@st.cache_data(ttl=3600)
def get_yearly_totals(agency_name, fy_start, fy_end):
    rows = []
    for fy in range(fy_start, fy_end + 1):
        try:
            df = get_state_spending(agency_name, fy)
            if not df.empty and "aggregated_amount" in df.columns:
                total = df["aggregated_amount"].fillna(0).sum()
                rows.append({"Fiscal Year": f"FY{fy}", "Total Obligations": total})
        except Exception:
            pass
    return pd.DataFrame(rows)

# ---------- Sidebar controls ----------
st.sidebar.header("Filters")
agency = st.sidebar.selectbox("Agency", list(AGENCIES.keys()))
agency_name = AGENCIES[agency]

fy = st.sidebar.slider("Fiscal Year (for map & recipients)", 2021, 2026, 2025)

st.sidebar.markdown("---")
st.sidebar.caption("Trend chart always shows FY2021–2026")
st.sidebar.markdown("---")
st.sidebar.info("Filtered to **Higher Education** recipients only")

# ---------- Fetch data ----------
with st.spinner(f"Fetching {agency} FY{fy} data for higher education..."):
    df_state = get_state_spending(agency_name, fy)
    df_recip = get_top_recipients(agency_name, fy)

# ---------- KPI row ----------
if not df_state.empty and "aggregated_amount" in df_state.columns:
    total = df_state["aggregated_amount"].fillna(0).sum()
    funded = df_state[df_state["aggregated_amount"].fillna(0) > 0].shape[0]
    top = df_state.loc[df_state["aggregated_amount"].fillna(0).idxmax()]

    c1, c2, c3 = st.columns(3)
    c1.metric("Total Obligations (Higher Ed)", f"${total/1e9:.2f}B")
    c2.metric("States & Territories with Funding", funded)
    c3.metric("Top State", f"{top['display_name']} (${top['aggregated_amount']/1e9:.2f}B)")

    # ---------- Map ----------
    st.subheader(f"{agency} — Obligations to Higher Education by State (FY{fy})")
    fig_map = px.choropleth(
        df_state,
        locations="shape_code",
        locationmode="USA-states",
        color="aggregated_amount",
        scope="usa",
        color_continuous_scale="Blues",
        labels={"aggregated_amount": "Obligations ($)"},
        hover_name="display_name"
    )
    fig_map.update_layout(
        margin=dict(l=20, r=20, t=10, b=10),
        height=500,
        geo=dict(
            lakecolor='rgba(255,255,255,0.5)',
            showlakes=True
        )
    )
    st.plotly_chart(fig_map, use_container_width=True)
else:
    st.warning(f"No higher education spending data found for {agency} FY{fy}")

# ---------- Two columns: Recipients + Trend ----------
col_left, col_right = st.columns(2)

with col_left:
    if not df_recip.empty and "amount" in df_recip.columns:
        st.subheader(f"Top 10 University Recipients (FY{fy})")
        df_recip = df_recip.sort_values("amount", ascending=True)
        name_col = "name" if "name" in df_recip.columns else df_recip.columns[0]
        fig_bar = px.bar(
            df_recip,
            x="amount",
            y=name_col,
            orientation="h",
            labels={"amount": "Obligations ($)", name_col: ""},
            color_discrete_sequence=["#1f4e79"]
        )
        fig_bar.update_layout(height=400, margin=dict(l=0, r=0, t=0, b=0))
        st.plotly_chart(fig_bar, use_container_width=True)
    else:
        st.info("No recipient data available")

with col_right:
    st.subheader(f"{agency} — Higher Ed Funding Trend (FY2021–2026)")
    with st.spinner("Loading trend data..."):
        df_trend = get_yearly_totals(agency_name, 2021, 2026)
    if not df_trend.empty:
        fig_trend = px.bar(
            df_trend,
            x="Fiscal Year",
            y="Total Obligations",
            text_auto=".2s",
            color_discrete_sequence=["#2c7fb8"]
        )
        fig_trend.update_layout(height=400, margin=dict(l=0, r=0, t=0, b=0))
        st.plotly_chart(fig_trend, use_container_width=True)
    else:
        st.info("No trend data available")

st.caption("Data source: USAspending.gov API · Filtered to higher education recipients")
