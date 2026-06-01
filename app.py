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
    "NSF": "National Science Foundation",
    "NASA": "National Aeronautics and Space Administration",
}

HE_RECIPIENT_TYPES = [
    "public_institution_of_higher_education",
    "private_institution_of_higher_education",
    "minority_serving_institution_of_higher_education",
]

# 2023 Census estimates – used for per-capita normalisation
STATE_POP = {
    "AL": 5108468, "AK": 733406, "AZ": 7431344, "AR": 3067732, "CA": 38965193,
    "CO": 5877610, "CT": 3617176, "DE": 1031890, "FL": 22610726, "GA": 11029227,
    "HI": 1435138, "ID": 1964726, "IL": 12549689, "IN": 6862199, "IA": 3207004,
    "KS": 2940546, "KY": 4526154, "LA": 4573749, "ME": 1395722, "MD": 6180253,
    "MA": 7001399, "MI": 10037261, "MN": 5737915, "MS": 2939690, "MO": 6196156,
    "MT": 1132812, "NE": 1978379, "NV": 3194176, "NH": 1402054, "NJ": 9290841,
    "NM": 2114371, "NY": 19571216, "NC": 10835491, "ND": 783926, "OH": 11785935,
    "OK": 4053824, "OR": 4233358, "PA": 12961683, "RI": 1095962, "SC": 5373555,
    "SD": 919318, "TN": 7126489, "TX": 30503301, "UT": 3417734, "VT": 647464,
    "VA": 8642274, "WA": 7812880, "WV": 1770071, "WI": 5910955, "WY": 584057,
    "DC": 678972, "PR": 3205691, "GU": 153836, "VI": 87146, "AS": 43895,
    "MP": 47329,
}


# ---------- Helpers ----------
def fmt_dollars(v):
    """Human-readable dollar string."""
    if abs(v) >= 1e9:
        return f"${v / 1e9:.2f}B"
    if abs(v) >= 1e6:
        return f"${v / 1e6:.2f}M"
    if abs(v) >= 1e3:
        return f"${v / 1e3:.1f}K"
    return f"${v:,.0f}"


def agency_filter(name):
    return [{"type": "awarding", "tier": "toptier", "name": name}]


def fy_dates(fy):
    return {"start_date": f"{fy - 1}-10-01", "end_date": f"{fy}-09-30"}


def base_filters(agency_name, fy, state_code=None):
    """Common filter block.  Optionally scoped to a single state."""
    dates = fy_dates(fy)
    f = {
        "time_period": [dates],
        "agencies": agency_filter(agency_name),
        "recipient_type_names": HE_RECIPIENT_TYPES,
    }
    if state_code:
        f["place_of_performance_locations"] = [
            {"country": "USA", "state": state_code}
        ]
    return f


@st.cache_data(ttl=3600)
def get_state_spending(agency_name, fy):
    payload = {
        "scope": "place_of_performance",
        "geo_layer": "state",
        "filters": base_filters(agency_name, fy),
    }
    r = requests.post(f"{BASE}/search/spending_by_geography/", json=payload)
    r.raise_for_status()
    return pd.DataFrame(r.json().get("results", []))


@st.cache_data(ttl=3600)
def get_top_recipients(agency_name, fy, state_code=None):
    payload = {
        "category": "recipient",
        "filters": base_filters(agency_name, fy, state_code=state_code),
        "limit": 10,
    }
    r = requests.post(f"{BASE}/search/spending_by_category/recipient", json=payload)
    r.raise_for_status()
    return pd.DataFrame(r.json().get("results", []))


@st.cache_data(ttl=3600)
def get_yearly_totals(agency_name, fy_start, fy_end, state_code=None):
    rows = []
    for fy in range(fy_start, fy_end + 1):
        try:
            if state_code:
                # Per-state trend: use the geography endpoint scoped to that state
                payload = {
                    "scope": "place_of_performance",
                    "geo_layer": "state",
                    "filters": base_filters(agency_name, fy, state_code=state_code),
                }
                resp = requests.post(
                    f"{BASE}/search/spending_by_geography/", json=payload
                )
                resp.raise_for_status()
                df = pd.DataFrame(resp.json().get("results", []))
            else:
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

per_capita = st.sidebar.toggle("Per-capita obligations", value=False)

# ---------- Fetch map data early so we can populate the state picker ----------
with st.spinner(f"Fetching {agency} FY{fy} data for higher education..."):
    df_state = get_state_spending(agency_name, fy)

# Build state list from live data
_state_options = ["All States"]
if not df_state.empty and "display_name" in df_state.columns and "shape_code" in df_state.columns:
    _funded = df_state[df_state["aggregated_amount"].fillna(0) > 0].sort_values("display_name")
    _state_options += [
        f"{row['display_name']} ({row['shape_code']})"
        for _, row in _funded.iterrows()
    ]

state_pick = st.sidebar.selectbox("Drill down to state", _state_options)
selected_state = None
if state_pick != "All States":
    selected_state = state_pick.split("(")[-1].rstrip(")")

st.sidebar.markdown("---")
st.sidebar.caption("Trend chart always shows FY2021–2026")
st.sidebar.markdown("---")
st.sidebar.info("Filtered to **Higher Education** recipients only")

# ---------- Per-capita enrichment ----------
if not df_state.empty and "aggregated_amount" in df_state.columns:
    df_state["population"] = df_state["shape_code"].map(STATE_POP)
    df_state["per_capita"] = (
        df_state["aggregated_amount"].fillna(0) / df_state["population"]
    )
    color_col = "per_capita" if per_capita else "aggregated_amount"
    color_label = "Per-Capita ($)" if per_capita else "Obligations ($)"

    # Clean hover text
    df_state["hover_text"] = df_state.apply(
        lambda r: (
            f"{r['display_name']}<br>"
            f"{fmt_dollars(r['aggregated_amount'])}"
            + (f"<br>{fmt_dollars(r['per_capita'])}/person" if per_capita else "")
        ),
        axis=1,
    )

# ---------- KPI row ----------
if not df_state.empty and "aggregated_amount" in df_state.columns:
    total = df_state["aggregated_amount"].fillna(0).sum()
    funded = df_state[df_state["aggregated_amount"].fillna(0) > 0].shape[0]
    top_idx = df_state[color_col].fillna(0).idxmax()
    top = df_state.loc[top_idx]

    c1, c2, c3 = st.columns(3)
    c1.metric("Total Obligations (Higher Ed)", fmt_dollars(total))
    c2.metric("States & Territories with Funding", funded)
    label = (
        f"{top['display_name']} ({fmt_dollars(top[color_col])}"
        + ("/person)" if per_capita else ")")
    )
    c3.metric("Top State" + (" by Per Capita" if per_capita else ""), label)

    # ---------- Map ----------
    map_title = f"{agency} — Obligations to Higher Education by State (FY{fy})"
    if per_capita:
        map_title += "  ·  Per Capita"
    st.subheader(map_title)

    fig_map = px.choropleth(
        df_state,
        locations="shape_code",
        locationmode="USA-states",
        color=color_col,
        scope="usa",
        color_continuous_scale="Blues",
        labels={color_col: color_label},
    )
    fig_map.update_traces(
        customdata=df_state[["hover_text"]].values,
        hovertemplate="%{customdata[0]}<extra></extra>",
    )
    fig_map.update_layout(
        margin=dict(l=20, r=20, t=10, b=10),
        height=500,
        geo=dict(lakecolor="rgba(255,255,255,0.5)", showlakes=True),
    )
    st.plotly_chart(fig_map, use_container_width=True)

    if selected_state:
        state_name = df_state.loc[
            df_state["shape_code"] == selected_state, "display_name"
        ]
        display = state_name.values[0] if len(state_name) > 0 else selected_state
        st.info(f"Showing recipients and trend for **{display}**")
else:
    st.warning(f"No higher education spending data found for {agency} FY{fy}")

# ---------- Two columns: Recipients + Trend ----------

col_left, col_right = st.columns(2)

with col_left:
    recip_label = (
        f"Top 10 University Recipients (FY{fy})"
        if not selected_state
        else f"Top Recipients in {selected_state} (FY{fy})"
    )
    st.subheader(recip_label)
    with st.spinner("Loading recipients..."):
        df_recip = get_top_recipients(agency_name, fy, state_code=selected_state)
    if not df_recip.empty and "amount" in df_recip.columns:
        df_recip = df_recip.sort_values("amount", ascending=True)
        name_col = "name" if "name" in df_recip.columns else df_recip.columns[0]
        fig_bar = px.bar(
            df_recip,
            x="amount",
            y=name_col,
            orientation="h",
            labels={"amount": "Obligations ($)", name_col: ""},
            color_discrete_sequence=["#1f4e79"],
        )
        fig_bar.update_layout(height=400, margin=dict(l=0, r=0, t=0, b=0))
        st.plotly_chart(fig_bar, use_container_width=True)
    else:
        st.info("No recipient data available for this selection")

with col_right:
    trend_label = (
        f"{agency} — Higher Ed Funding Trend (FY2021–2026)"
        if not selected_state
        else f"{agency} — {selected_state} Funding Trend (FY2021–2026)"
    )
    st.subheader(trend_label)
    with st.spinner("Loading trend data..."):
        df_trend = get_yearly_totals(agency_name, 2021, 2026, state_code=selected_state)
    if not df_trend.empty:
        fig_trend = px.bar(
            df_trend,
            x="Fiscal Year",
            y="Total Obligations",
            text_auto=".2s",
            color_discrete_sequence=["#2c7fb8"],
        )
        fig_trend.update_layout(height=400, margin=dict(l=0, r=0, t=0, b=0))
        st.plotly_chart(fig_trend, use_container_width=True)
    else:
        st.info("No trend data available for this selection")

st.caption("Data source: USAspending.gov API · Filtered to higher education recipients")
