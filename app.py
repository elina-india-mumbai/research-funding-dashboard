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

# 50 states + DC define the "national" aggregation. Keeping numerator
# (obligations) and denominator (population) on the SAME geography is what
# makes the population-weighted national per-capita benchmark defensible.
NATIONAL_CODES = [
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "ID",
    "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS",
    "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK",
    "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV",
    "WI", "WY", "DC",
]
NATIONAL_POP = sum(STATE_POP[c] for c in NATIONAL_CODES)


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


@st.cache_data(ttl=3600)
def get_ms_vs_national_percapita(fy_start, fy_end):
    """For every agency and fiscal year, compute Mississippi vs population-weighted
    national per-capita obligations to higher education.

    This is pure re-aggregation of the SAME USAspending obligations the map already
    uses — no new data source. For each agency-year it reuses get_state_spending()
    (cached), then:
        National (pop-weighted) = sum(obligations over 50 states + DC)
                                  / sum(population over 50 states + DC)
        Mississippi             = MS obligations / MS population
    """
    rows = []
    for code, full_name in AGENCIES.items():
        for fy in range(fy_start, fy_end + 1):
            try:
                df = get_state_spending(full_name, fy)
                if df.empty or "aggregated_amount" not in df.columns:
                    continue
                df = df.copy()
                df["amt"] = df["aggregated_amount"].fillna(0)

                nat_total = df[df["shape_code"].isin(NATIONAL_CODES)]["amt"].sum()
                nat_pc = nat_total / NATIONAL_POP if NATIONAL_POP else 0.0

                ms_amt = df.loc[df["shape_code"] == "MS", "amt"].sum()
                ms_pc = ms_amt / STATE_POP["MS"]

                rows.append({
                    "Agency": code, "Fiscal Year": f"FY{fy}",
                    "Series": "Mississippi", "Per-Capita ($)": ms_pc,
                })
                rows.append({
                    "Agency": code, "Fiscal Year": f"FY{fy}",
                    "Series": "National (pop-weighted)", "Per-Capita ($)": nat_pc,
                })
            except Exception:
                pass
    return pd.DataFrame(rows)


# ---------- Sidebar controls ----------
st.sidebar.header("Filters")
agency = st.sidebar.selectbox("Agency", list(AGENCIES.keys()))
agency_name = AGENCIES[agency]
fy = st.sidebar.slider("Fiscal Year (for map & recipients)", 2021, 2026, 2025)

# Per-capita defaults ON so the dashboard opens on the Mississippi story.
per_capita = st.sidebar.toggle("Per-capita obligations", value=True)

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

# Default the drill-down to Mississippi if it is present in the live data.
_default_idx = 0
for _i, _opt in enumerate(_state_options):
    if _opt.endswith("(MS)"):
        _default_idx = _i
        break
state_pick = st.sidebar.selectbox("Drill down to state", _state_options, index=_default_idx)
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

# ---------- Mississippi vs National: per-capita trend by agency ----------
# This is the centerpiece view for the 3-minute talk. One small panel per agency,
# Mississippi (solid) vs population-weighted national per-capita (dashed),
# FY2021–2026. Per-agency y-axes so each agency's gap is visible.
st.markdown("---")
st.subheader("Mississippi vs National — Per-Capita Funding by Agency (FY2021–2026)")
st.caption(
    "National benchmark = total obligations to the 50 states + DC ÷ their combined "
    "population (population-weighted). Mississippi = MS obligations ÷ MS population. "
    "Same USAspending obligations as the map above, re-aggregated per capita."
)

with st.spinner("Building Mississippi-vs-national comparison across all agencies (first run is slow, then cached)..."):
    df_ms = get_ms_vs_national_percapita(2021, 2026)

if not df_ms.empty:
    fig_ms = px.line(
        df_ms,
        x="Fiscal Year",
        y="Per-Capita ($)",
        color="Series",
        facet_col="Agency",
        facet_col_wrap=3,
        markers=True,
        category_orders={"Agency": list(AGENCIES.keys())},
        color_discrete_map={
            "Mississippi": "#c0392b",
            "National (pop-weighted)": "#2c3e50",
        },
    )
    # National line dashed so Mississippi reads as the focus series.
    for tr in fig_ms.data:
        if isinstance(tr.name, str) and tr.name.startswith("National"):
            tr.line.dash = "dash"
    # Strip the "Agency=" prefix plotly puts on facet titles.
    fig_ms.for_each_annotation(lambda a: a.update(text=a.text.split("=")[-1]))
    # Independent y-axes per agency so small-budget agencies aren't flattened.
    fig_ms.update_yaxes(matches=None, showticklabels=True)
    fig_ms.update_layout(
        height=560,
        margin=dict(l=10, r=10, t=46, b=10),
        legend_title_text="",
        legend=dict(orientation="h", yanchor="bottom", y=1.04, xanchor="right", x=1),
    )
    st.plotly_chart(fig_ms, use_container_width=True)
    st.caption(
        "Mississippi (solid red) vs national per-capita (dashed). Note: y-axes "
        "differ across agencies so each agency's gap is legible. "
        "Data source: USAspending.gov."
    )
else:
    st.info("No data available to build the Mississippi-vs-national comparison.")

st.caption("Data source: USAspending.gov API · Filtered to higher education recipients")
