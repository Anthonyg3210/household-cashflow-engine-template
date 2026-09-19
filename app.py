"""Household Cashflow Engine — 3-Year View (Streamlit)."""
from __future__ import annotations

import json
from calendar import monthrange, month_name
from datetime import date, datetime, timedelta
from itertools import groupby
from pathlib import Path

import pandas as pd
import streamlit as st

from engine import db
from engine.project import (
    ScenarioDelta,
    compare_scenarios,
    project,
    format_pitfall_ribbon,
    year_pitfall_scorecard,
    filter_months_for_year,
    year_scorecard_kpis,
    breach_autopsy,
)
from engine.cash_cushion import primary_red_streak
from engine.mitigation import (
    mitigation_suggestions,
    apply_mitigation_db,
    category_nature,
    list_applied_mitigations,
    format_mitigation_oneliner,
)
from engine.mitigation_ui_state import (
    is_dismissed,
    dismiss_month,
    undismiss_month,
    clear_dismissed_if_not_red,
    plain_english_mitigation,
    applied_checklist_line,
)
from engine.calendar_view import (
    effective_day_flows,
    BUCKET_INCOME,
    BUCKET_FIXED,
    BUCKET_FLEXIBLE,
    BUCKET_LIFESTYLE,
    BUCKET_OTHER,
    month_days_index,
    available_calendar_months,
    month_bill_checklist,
    split_month_checklist,
    type_display_label,
    month_money_totals,
    month_week_lanes,
    checklist_for_dates,
    pill_bucket_counts,
    week_playbook_sections,
    bifurcate_bill_rows,
)
from engine.seed_load import ensure_seeded, import_seed, resolve_seed_dir
from engine.bank_import import (
    import_csv,
    write_import_report,
    CSV_SOURCE,
    BLACK_CARD_SOURCE,
    BLACK_CARD_DISPLAY,
    import_black_card_csv,
    load_black_card_snapshot,
    load_black_card_budget_context,
    allowance_budget_for_month,
    ALLOWANCE_3500_FROM,
    is_card_purchase,
    merchant_stem,
)
from engine.rewards_optimize import (
    score_family_card_spend,
    format_refresh_line,
)
from engine.due_date_learn import (
    learn_from_actuals,
    apply_learned_doms,
    load_payment_preferences,
    LEARNED_PATH,
)
from engine.net_worth import load_snapshot, save_snapshot, format_balance_display
from engine.debt_paydown import (
    load_debts,
    save_debts,
    get_debt,
    schedule_for_debt,
    compare_schedules,
    balance_series,
    excel_checkpoint_caption,
    parse_lump_date,
    update_debt_balance,
)
from engine.retirement import (
    load_plan as load_retirement_plan,
    save_plan as save_retirement_plan,
    load_retirement_accounts,
    current_retirement_assets,
    nest_egg_target,
    classic_25x,
    evaluate_brackets,
    evaluate_lifestyle_tiles,
    derive_lifestyle_need_annual,
    income_replacement_annual,
    build_month_totals_from_checklists,
    course_suggestions as retirement_course_suggestions,
    load_snapshot as load_retirement_snapshot,
    save_snapshot as save_retirement_snapshot,
    build_snapshot as build_retirement_snapshot,
    append_history as append_retirement_history,
    warehouse_status,
    taxable_bridge_months,
    lifestyle_levels,
    format_money as ret_format_money,
    format_money_compact as ret_format_money_compact,
    format_pct as ret_format_pct,
    format_years as ret_format_years,
    format_months as ret_format_months,
    AGE_AWARE_SWR,
    AGE_AWARE_MULTIPLIER,
    DEFAULT_COMFORT_ANNUAL,
    DEFAULT_STATED_MONTHLY,
    HEALTHCARE_TEMP_ADDER_ANNUAL,
    WITHDRAWAL_PRESETS,
    DEFAULT_AGES as RETIREMENT_DEFAULT_AGES,
)
from engine.tax_layer import (
    load_tax_profile,
    load_plan_features,
    build_base_taxable_2026,
    conversion_scenarios,
    path_summaries,
    worth_it_verdict,
    tax_layer_bundle,
    compute_tax,
    marginal_bracket_info,
)
from engine import insights as insights_eng
from engine.insights import (
    STREAM_ORDER,
    STREAM_SHORT,
    STREAM_PRIMARY,
    STREAM_SECONDARY,
    STREAM_SIDE_GIG,
    STREAM_OTHER,
    GOAL_NARRATIVE,
    SIDE_GIG_PLAN_END_MONTH,
    SECONDARY_SUNSET_MONTH,
    FEATURED_EXPENSE_PARENTS,
    DISCRETIONARY_EXCLUDE_PARENTS,
    DEFAULT_MOM_VARIANCE_THRESHOLD,
    DEFAULT_QOQ_VARIANCE_THRESHOLD,
    MOM_THRESHOLD_RANGE,
    QOQ_THRESHOLD_RANGE,
    BUDGET_LIMITATIONS_NOTE,
)
from engine.forecast_guard import (
    gap_prompts,
    run_coverage_check,
    summarize_coverage,
)
from engine.variable_amounts import (
    oct_plus_fpl_water_totals,
    plain_english_variable_detail_lines,
    plain_english_variable_sentence,
    variable_ui_rows,
)

st.set_page_config(
    page_title="Household Cashflow Engine",
    page_icon="💰",
    layout="wide",
)


def _inject_app_wallpaper() -> None:
    """Subtle executive wallpaper + glass panels (CSS only; partner-friendly clarity)."""
    st.markdown(
        """
<style>
/* Soft finance-friendly gradient + faint geometric grid */
[data-testid="stAppViewContainer"] {
  background:
    linear-gradient(135deg, rgba(232, 240, 248, 0.92) 0%, rgba(245, 248, 252, 0.95) 45%, rgba(236, 244, 239, 0.92) 100%),
    repeating-linear-gradient(
      0deg,
      transparent,
      transparent 47px,
      rgba(90, 110, 140, 0.035) 47px,
      rgba(90, 110, 140, 0.035) 48px
    ),
    repeating-linear-gradient(
      90deg,
      transparent,
      transparent 47px,
      rgba(90, 110, 140, 0.035) 47px,
      rgba(90, 110, 140, 0.035) 48px
    ) !important;
  background-attachment: fixed !important;
}
[data-testid="stHeader"] {
  background: rgba(245, 248, 252, 0.72) !important;
  backdrop-filter: blur(8px);
}
/* Sidebar: soft tint to match */
section[data-testid="stSidebar"] {
  background: linear-gradient(180deg, #e8eef6 0%, #f2f6fa 55%, #eef5f1 100%) !important;
  border-right: 1px solid rgba(120, 140, 170, 0.18);
}
section[data-testid="stSidebar"] > div {
  background: transparent !important;
}
/* Readable glass / white panels */
div[data-testid="stVerticalBlockBorderWrapper"],
div[data-testid="stExpander"],
div[data-testid="metric-container"],
div[data-testid="stMetric"] {
  background: rgba(255, 255, 255, 0.82) !important;
  backdrop-filter: blur(6px);
  border-radius: 12px !important;
  box-shadow: 0 2px 12px rgba(40, 60, 90, 0.06);
}
/* Keep main block content readable on wallpaper */
.block-container {
  background: transparent !important;
}
</style>
        """,
        unsafe_allow_html=True,
    )


_inject_app_wallpaper()


@st.cache_resource
def get_conn():
    # Restore tracked bootstrap BEFORE opening the connection (Cloud empty-DB fix).
    # ensure_seeded always re-applies excel_parity so rule overlays (Demo Cleaners, etc.)
    # land on existing Cloud DBs without requiring a full bootstrap replace.
    db.maybe_restore_from_bootstrap()
    conn = db.connect()
    ensure_seeded(conn)
    return conn



def money(x):
    if x is None:
        return "—"
    return f"${x:,.2f}"


def _md(s) -> str:
    """Escape $ for Streamlit markdown/captions (bare $ becomes KaTeX)."""
    if s is None:
        return ""
    return str(s).replace("$", r"\$")



def labeled_bars(
    df,
    *,
    x_col,
    y_col,
    color_col=None,
    horizontal=False,
    height=260,
    title=None,
    x_sort=None,
    color_domain=None,
    color_range=None,
    money_format=True,
    stack=None,
):
    """Altair bar chart with face-value dollar labels + hover tooltips.

    Prefer this over ``st.bar_chart`` (which cannot label bars).
    - Vertical single-series: label above each bar.
    - Horizontal: label at end of bar.
    - Grouped (color_col, stack is None): label each bar via xOffset/yOffset.
    - Stacked (stack="zero"/True): segment labels when share ≥ 12%, plus stack total on top.
    """
    import altair as alt

    if df is None or getattr(df, "empty", True):
        st.caption("No data to chart.")
        return None

    plot = df.copy()
    plot[y_col] = pd.to_numeric(plot[y_col], errors="coerce").fillna(0.0)

    def _money_txt(v: float) -> str:
        if abs(float(v)) < 0.5:
            return ""
        if money_format:
            return f"${float(v):,.0f}"
        return f"{float(v):,.0f}"

    val_fmt = "$,.0f" if money_format else ",.0f"
    tip_title = "$" if money_format else "Value"
    tooltips = [
        alt.Tooltip(f"{x_col}:N", title=str(x_col).replace("_", " ").title()),
    ]
    if color_col:
        tooltips.append(
            alt.Tooltip(f"{color_col}:N", title=str(color_col).replace("_", " ").title())
        )
    tooltips.append(alt.Tooltip(f"{y_col}:Q", format=val_fmt, title=tip_title))

    do_stack = bool(stack) and color_col is not None
    if stack is True:
        stack = "zero"

    color_enc = None
    if color_col:
        scale_kwargs = {}
        if color_domain is not None:
            scale_kwargs["domain"] = list(color_domain)
        if color_range is not None:
            scale_kwargs["range"] = list(color_range)
        color_kwargs = dict(
            title=str(color_col).replace("_", " ").title(),
            legend=alt.Legend(orient="right"),
        )
        if color_domain is not None:
            color_kwargs["sort"] = list(color_domain)
        if scale_kwargs:
            color_kwargs["scale"] = alt.Scale(**scale_kwargs)
        color_enc = alt.Color(f"{color_col}:N", **color_kwargs)

    x_sort_arg = list(x_sort) if x_sort is not None else None

    layers = []
    if do_stack:
        # Share of stack for sparse segment labels
        _gt = plot.groupby(x_col)[y_col].transform("sum")
        plot = plot.copy()
        plot["_seg_label"] = [
            _money_txt(v) if (t > 0 and (100.0 * float(v) / float(t)) >= 12.0) else ""
            for v, t in zip(plot[y_col], _gt)
        ]
        if color_domain is not None:
            ord_map = {s: i for i, s in enumerate(color_domain)}
            plot["_stack_ord"] = plot[color_col].map(lambda c: ord_map.get(c, 999))
        else:
            cats = list(dict.fromkeys(plot[color_col].tolist()))
            ord_map = {s: i for i, s in enumerate(cats)}
            plot["_stack_ord"] = plot[color_col].map(ord_map)

        if horizontal:
            bar = (
                alt.Chart(plot)
                .mark_bar()
                .encode(
                    y=alt.Y(f"{x_col}:N", title=None, sort=x_sort_arg),
                    x=alt.X(f"{y_col}:Q", title=tip_title if money_format else None, stack=stack),
                    color=color_enc,
                    order=alt.Order("_stack_ord:Q"),
                    tooltip=tooltips,
                )
            )
            seg = (
                alt.Chart(plot)
                .mark_text(baseline="middle", fontSize=10, color="white")
                .encode(
                    y=alt.Y(f"{x_col}:N", sort=x_sort_arg),
                    x=alt.X(f"{y_col}:Q", stack=stack),
                    detail=f"{color_col}:N",
                    order=alt.Order("_stack_ord:Q"),
                    text="_seg_label:N",
                )
            )
            totals = plot.groupby(x_col, as_index=False)[y_col].sum()
            totals["_tot_label"] = totals[y_col].map(_money_txt)
            tot = (
                alt.Chart(totals)
                .mark_text(align="left", dx=4, fontSize=11, fontWeight="bold", color="#1e293b")
                .encode(
                    y=alt.Y(f"{x_col}:N", sort=x_sort_arg),
                    x=alt.X(f"{y_col}:Q"),
                    text="_tot_label:N",
                )
            )
            layers = [bar, seg, tot]
        else:
            bar = (
                alt.Chart(plot)
                .mark_bar()
                .encode(
                    x=alt.X(f"{x_col}:N", title=None, sort=x_sort_arg),
                    y=alt.Y(f"{y_col}:Q", title=tip_title if money_format else None, stack=stack),
                    color=color_enc,
                    order=alt.Order("_stack_ord:Q"),
                    tooltip=tooltips,
                )
            )
            seg = (
                alt.Chart(plot)
                .mark_text(baseline="middle", fontSize=10, color="white")
                .encode(
                    x=alt.X(f"{x_col}:N", sort=x_sort_arg),
                    y=alt.Y(f"{y_col}:Q", stack=stack),
                    detail=f"{color_col}:N",
                    order=alt.Order("_stack_ord:Q"),
                    text="_seg_label:N",
                )
            )
            totals = plot.groupby(x_col, as_index=False)[y_col].sum()
            totals["_tot_label"] = totals[y_col].map(_money_txt)
            tot = (
                alt.Chart(totals)
                .mark_text(dy=-8, fontSize=11, fontWeight="bold", color="#1e293b", baseline="bottom")
                .encode(
                    x=alt.X(f"{x_col}:N", sort=x_sort_arg),
                    y=alt.Y(f"{y_col}:Q"),
                    text="_tot_label:N",
                )
            )
            layers = [bar, seg, tot]
    else:
        plot = plot.copy()
        plot["_label"] = plot[y_col].map(_money_txt)
        grouped = color_col is not None

        if horizontal:
            y_enc = alt.Y(f"{x_col}:N", title=None, sort=x_sort_arg)
            x_enc = alt.X(f"{y_col}:Q", title=tip_title if money_format else None)
            encode_bar = {"y": y_enc, "x": x_enc, "tooltip": tooltips}
            encode_txt = {
                "y": alt.Y(f"{x_col}:N", sort=x_sort_arg),
                "x": alt.X(f"{y_col}:Q"),
                "text": "_label:N",
            }
            if grouped:
                encode_bar["color"] = color_enc
                encode_bar["yOffset"] = f"{color_col}:N"
                encode_txt["yOffset"] = f"{color_col}:N"
                if color_domain is not None:
                    encode_bar["yOffset"] = alt.YOffset(f"{color_col}:N", sort=list(color_domain))
                    encode_txt["yOffset"] = alt.YOffset(f"{color_col}:N", sort=list(color_domain))
            bar = alt.Chart(plot).mark_bar().encode(**encode_bar)
            txt = (
                alt.Chart(plot)
                .mark_text(align="left", dx=4, fontSize=11, color="#334155", baseline="middle")
                .encode(**encode_txt)
            )
            layers = [bar, txt]
        else:
            x_enc = alt.X(f"{x_col}:N", title=None, sort=x_sort_arg)
            y_enc = alt.Y(f"{y_col}:Q", title=tip_title if money_format else None)
            encode_bar = {"x": x_enc, "y": y_enc, "tooltip": tooltips}
            encode_txt = {
                "x": alt.X(f"{x_col}:N", sort=x_sort_arg),
                "y": alt.Y(f"{y_col}:Q"),
                "text": "_label:N",
            }
            if grouped:
                encode_bar["color"] = color_enc
                if color_domain is not None:
                    encode_bar["xOffset"] = alt.XOffset(f"{color_col}:N", sort=list(color_domain))
                    encode_txt["xOffset"] = alt.XOffset(f"{color_col}:N", sort=list(color_domain))
                else:
                    encode_bar["xOffset"] = f"{color_col}:N"
                    encode_txt["xOffset"] = f"{color_col}:N"
            bar = alt.Chart(plot).mark_bar().encode(**encode_bar)
            txt = (
                alt.Chart(plot)
                .mark_text(dy=-8, fontSize=11, color="#334155", baseline="bottom")
                .encode(**encode_txt)
            )
            layers = [bar, txt]

    chart = layers[0]
    for layer in layers[1:]:
        chart = chart + layer
    props = {"height": height}
    if title:
        props["title"] = title
    chart = chart.properties(**props)
    st.altair_chart(chart, use_container_width=True)
    return chart


def _pict_card_css() -> str:
    """Shared calm pictorial summary-card styles (Bills + Dashboard)."""
    return """
<style>
.pict-row {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: 0.75rem;
  margin: 0.35rem 0 1rem 0;
}
.pict-card {
  border-radius: 16px;
  padding: 0.95rem 1rem 0.85rem;
  background: linear-gradient(160deg, #f7f9fc 0%, #eef3f8 100%);
  border: 1px solid #d7dee8;
  box-shadow: 0 1px 2px rgba(40, 55, 80, 0.04);
  min-height: 7.2rem;
  display: flex;
  flex-direction: column;
  gap: 0.2rem;
}
.pict-card.pict-income {
  background: linear-gradient(160deg, #e8f8ef 0%, #f4fcf7 100%);
  border-color: #9ad4b0;
}
.pict-card.pict-expense {
  background: linear-gradient(160deg, #f7f4ef 0%, #fbf8f3 100%);
  border-color: #e2d5c3;
}
.pict-card.pict-brokerage {
  background: linear-gradient(160deg, #eef2fb 0%, #f5f7fc 100%);
  border-color: #c5cfe6;
}
.pict-card.pict-savings {
  background: linear-gradient(160deg, #eef8f6 0%, #f4fbf9 100%);
  border-color: #b9ddd4;
}
.pict-emoji { font-size: 1.55rem; line-height: 1.1; margin-bottom: 0.15rem; }
.pict-label {
  font-size: 0.78rem; font-weight: 650; letter-spacing: 0.03em;
  text-transform: uppercase; color: #5b6575;
}
.pict-value {
  font-size: 1.35rem; font-weight: 750; color: #1f2937;
  letter-spacing: -0.01em; margin-top: 0.15rem;
}
.pict-value.pict-empty { color: #9aa3b2; font-weight: 600; font-size: 1.2rem; }
.pict-value.pict-pos { color: #1b6b3a; }
.pict-value.pict-neg { color: #7a4a1e; }
.pict-sub { font-size: 0.78rem; color: #6b7280; margin-top: 0.1rem; }
</style>
"""


def _pict_card_html(
    *,
    emoji: str,
    label: str,
    value_html: str,
    sub: str = "",
    kind: str = "",
) -> str:
    cls = f"pict-card pict-{kind}" if kind else "pict-card"
    # Escape $ in sub copy so Streamlit does not render green KaTeX in HTML cards.
    sub_safe = str(sub).replace("$", "&#36;") if sub else ""
    sub_html = f'<div class="pict-sub">{sub_safe}</div>' if sub_safe else ""
    return (
        f'<div class="{cls}">'
        f'<div class="pict-emoji">{emoji}</div>'
        f'<div class="pict-label">{label}</div>'
        f'<div class="pict-value">{value_html}</div>'
        f"{sub_html}"
        f"</div>"
    )


def _fmt_pict_money(amount: float | None, *, signed: str | None = None, empty: str = "—") -> str:
    """signed: 'pos' force +, 'neg' show as outflow magnitude, None plain money.
    Uses &#36; so Streamlit markdown does not treat $ as KaTeX."""
    if amount is None:
        return f'<span class="pict-empty">{empty}</span>'
    amt = float(amount)
    if signed == "neg":
        return f'<span class="pict-neg">−&#36;{abs(amt):,.2f}</span>'
    if signed == "pos":
        return f'<span class="pict-pos">+&#36;{amt:,.2f}</span>'
    return f"&#36;{amt:,.2f}"



def _year_scorecard_css() -> str:
    """Green/red year pitfall scorecard chips (Dashboard)."""
    return """
<style>
.ysc-row {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: 0.75rem;
  margin: 0.35rem 0 0.35rem 0;
}
.ysc-card {
  border-radius: 16px;
  padding: 0.95rem 0.85rem 0.85rem;
  text-align: center;
  border: 1px solid #d7dee8;
  box-shadow: 0 1px 2px rgba(40, 55, 80, 0.05);
  min-height: 8.2rem;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.2rem;
}
.ysc-card.ysc-good {
  background: linear-gradient(160deg, #e6f7ed 0%, #f3fbf6 100%);
  border-color: #8ecfa6;
}
.ysc-card.ysc-bad {
  background: linear-gradient(160deg, #fdeceb 0%, #fff6f5 100%);
  border-color: #e5a39a;
}
.ysc-emoji { font-size: 1.85rem; line-height: 1.1; }
.ysc-year {
  font-size: 1.45rem; font-weight: 780; letter-spacing: -0.02em;
  color: #1f2937; margin-top: 0.1rem;
}
.ysc-detail {
  font-size: 0.92rem; font-weight: 650; color: #374151;
  margin-top: 0.15rem; line-height: 1.25;
}
.ysc-card.ysc-good .ysc-detail { color: #1b6b3a; }
.ysc-card.ysc-bad .ysc-detail { color: #9b2c2c; }
.ysc-count { font-size: 0.75rem; color: #6b7280; margin-top: 0.15rem; }
</style>
"""


def _year_scorecard_card_html(entry: dict) -> str:
    """One pictorial year chip from ``year_pitfall_scorecard``."""
    bad = bool(entry.get("is_bad"))
    cls = "ysc-card ysc-bad" if bad else "ysc-card ysc-good"
    emoji = "⚠️" if bad else "✅"
    year = entry["year"]
    detail = entry.get("detail") or ("All clear" if not bad else "")
    n = int(entry.get("red_month_count") or 0)
    if bad:
        count = f"{n} red month" + ("" if n == 1 else "s")
    else:
        count = "No cash troughs"
    return (
        f'<div class="{cls}">'
        f'<div class="ysc-emoji">{emoji}</div>'
        f'<div class="ysc-year">{year}</div>'
        f'<div class="ysc-detail">{detail}</div>'
        f'<div class="ysc-count">{count}</div>'
        f"</div>"
    )


def _render_year_pitfall_scorecard(
    months_all: list,
    years_present: list,
    *,
    warning_threshold: float,
) -> None:
    """Pictorial year scorecard + optional click-to-filter buttons."""
    scorecard = year_pitfall_scorecard(months_all, key="days_negative", years=years_present)
    warn_sc = year_pitfall_scorecard(months_all, key="days_warning", years=years_present)

    st.markdown("### Year pitfall scorecard")
    st.caption(
        "Green = no negative days that year · Red = at least one cash trough"
    )
    st.markdown(_year_scorecard_css(), unsafe_allow_html=True)

    if not scorecard:
        st.info("No projection months in horizon yet.")
        return

    # Visual cards in a responsive row
    st.markdown(
        '<div class="ysc-row">'
        + "".join(_year_scorecard_card_html(e) for e in scorecard)
        + "</div>",
        unsafe_allow_html=True,
    )

    # Clickable year filters (sets the Dashboard year selectbox)
    btn_cols = st.columns(len(scorecard))
    for col, entry in zip(btn_cols, scorecard):
        y = str(entry["year"])
        label = f"View {y}"
        selected = st.session_state.get("dash_year_filter") == y
        with col:
            if st.button(
                label,
                key=f"ysc_filter_{y}",
                use_container_width=True,
                type="primary" if selected else "secondary",
            ):
                st.session_state.dash_year_filter = y
                st.rerun()

    # Keep warning-threshold context when it differs from hard negatives
    warn_differs = any(
        (a["bad_months"] != b["bad_months"])
        for a, b in zip(scorecard, warn_sc)
    )
    if warn_differs:
        warn_ribbon = format_pitfall_ribbon(
            months_all, key="days_warning", years=years_present
        )
        st.caption(
            _md(
                f"Warning-threshold months (EOD < {money(warning_threshold)}): {warn_ribbon}"
            )
        )
    else:
        st.caption(
            _md(
                f"Warning-threshold months (EOD < {money(warning_threshold)}) "
                "match the red years above."
            )
        )



def _red_streak_css() -> str:
    """Pictorial cash-cushion / red-streak executive card (Dashboard)."""
    return """
<style>
.rsc-wrap { margin: 0.5rem 0 1rem 0; }
.rsc-card {
  border-radius: 18px;
  padding: 1.1rem 1.25rem 1rem;
  border: 1px solid #d7dee8;
  box-shadow: 0 1px 3px rgba(40, 55, 80, 0.06);
}
.rsc-card.rsc-good {
  background: linear-gradient(160deg, #e6f7ed 0%, #f3fbf6 100%);
  border-color: #8ecfa6;
}
.rsc-card.rsc-warn {
  background: linear-gradient(160deg, #fff6e8 0%, #fffbf3 100%);
  border-color: #e6c48a;
}
.rsc-card.rsc-bad {
  background: linear-gradient(160deg, #fdeceb 0%, #fff6f5 100%);
  border-color: #e5a39a;
}
.rsc-head {
  display: flex; align-items: center; gap: 0.55rem;
  margin-bottom: 0.55rem;
}
.rsc-emoji { font-size: 1.75rem; line-height: 1; }
.rsc-title {
  font-size: 1.05rem; font-weight: 750; color: #1f2937;
  letter-spacing: -0.01em;
}
.rsc-metrics {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
  gap: 0.65rem;
  margin: 0.35rem 0 0.55rem 0;
}
.rsc-metric {
  text-align: center;
  padding: 0.55rem 0.4rem;
  border-radius: 12px;
  background: rgba(255,255,255,0.55);
  border: 1px solid rgba(0,0,0,0.04);
}
.rsc-metric-label {
  font-size: 0.72rem; font-weight: 650; letter-spacing: 0.04em;
  text-transform: uppercase; color: #6b7280;
}
.rsc-metric-value {
  font-size: 1.55rem; font-weight: 780; color: #1f2937;
  letter-spacing: -0.02em; margin-top: 0.15rem; line-height: 1.15;
}
.rsc-card.rsc-bad .rsc-metric-value { color: #9b2c2c; }
.rsc-card.rsc-warn .rsc-metric-value { color: #9a5b12; }
.rsc-card.rsc-good .rsc-metric-value { color: #1b6b3a; }
.rsc-tip {
  font-size: 1.02rem; font-weight: 650; color: #1f2937;
  line-height: 1.35; margin-top: 0.25rem;
}
.rsc-hint {
  font-size: 0.82rem; color: #6b7280; margin-top: 0.45rem; line-height: 1.35;
}
</style>
"""


def _render_red_streak_cushion_card(months_all: list) -> None:
    """Executive cash-cushion card: start month, streak length, trough, set-aside $."""
    st.markdown("### Cash cushion")
    st.caption(
        "If checking goes red for several months in a row, this shows how much to set aside first."
    )
    st.markdown(_red_streak_css(), unsafe_allow_html=True)

    streak = primary_red_streak(months_all, key="days_negative", clear_to=0.0)
    if not streak:
        html = (
            '<div class="rsc-wrap"><div class="rsc-card rsc-good">'
            '<div class="rsc-head">'
            '<div class="rsc-emoji">✅</div>'
            '<div class="rsc-title">No red streak ahead</div>'
            "</div>"
            '<div class="rsc-tip">Checking stays clear — no cash cushion needed right now.</div>'
            '<div class="rsc-hint">Flexible moves (like Savings timing) still help keep the runway smooth.</div>'
            "</div></div>"
        )
        st.markdown(html, unsafe_allow_html=True)
        return

    length = int(streak["length"])
    # Amber for a single red month; red for multi-month consecutive streak
    tone = "rsc-bad" if length >= 2 else "rsc-warn"
    emoji = "🔴" if length >= 2 else "🟠"
    title = (
        f"Red streak starting {streak['start_month_name']}"
        if length >= 2
        else f"Red month: {streak['start_month_name']}"
    )
    trough = float(streak["deepest_trough"])
    cushion = float(streak["cushion_rounded"])
    trough_html = (
        f"−&#36;{abs(trough):,.0f}" if trough < 0 else f"&#36;{trough:,.0f}"
    )
    cushion_html = f"&#36;{cushion:,.0f}"
    tip = str(streak["plain_english"]).replace("$", "&#36;")
    months_label = f"{length} month" + ("" if length == 1 else "s")
    html = (
        f'<div class="rsc-wrap"><div class="rsc-card {tone}">'
        f'<div class="rsc-head">'
        f'<div class="rsc-emoji">{emoji}</div>'
        f'<div class="rsc-title">{title}</div>'
        f"</div>"
        f'<div class="rsc-metrics">'
        f'<div class="rsc-metric"><div class="rsc-metric-label">Starts</div>'
        f'<div class="rsc-metric-value">{streak["start_month_name"]}</div></div>'
        f'<div class="rsc-metric"><div class="rsc-metric-label">In a row</div>'
        f'<div class="rsc-metric-value">{months_label}</div></div>'
        f'<div class="rsc-metric"><div class="rsc-metric-label">Deepest trough</div>'
        f'<div class="rsc-metric-value">{trough_html}</div></div>'
        f'<div class="rsc-metric"><div class="rsc-metric-label">Cash cushion</div>'
        f'<div class="rsc-metric-value">{cushion_html}</div></div>'
        f"</div>"
        f'<div class="rsc-tip">{tip}</div>'
        f'<div class="rsc-hint">Tip: flexible moves (Savings timing) on the Mitigation cards may also help clear red days.</div>'
        f"</div></div>"
    )
    st.markdown(html, unsafe_allow_html=True)



def _render_summary_icon_cards(
    *,
    money_in: float | None = None,
    money_out: float | None = None,
    include_flow: bool = True,
    month_label: str | None = None,
    snapshot: dict | None = None,
    empty_balance_copy: str = "—",
    live_checking: float | None = None,
    live_checking_as_of: str | None = None,
    projected_month_end: float | None = None,
    projected_month_label: str | None = None,
):
    """Pictorial summary cards — income/expense + balances (+ optional Chase / month-end)."""
    snap = snapshot if snapshot is not None else load_snapshot()
    fid = snap.get("fidelity_brokerage_balance")
    sav = snap.get("savings_balance")
    as_of = snap.get("balances_as_of")
    as_of_sub = f"as of {as_of}" if as_of else "Not set yet"

    cards = []
    if include_flow:
        flow_sub = month_label or "Selected month"
        cards.append(
            _pict_card_html(
                emoji="💵",
                label="Income this month",
                value_html=_fmt_pict_money(money_in, signed="pos"),
                sub=flow_sub,
                kind="income",
            )
        )
        cards.append(
            _pict_card_html(
                emoji="🏠",
                label="Household expenses",
                value_html=_fmt_pict_money(money_out, signed="neg"),
                sub=flow_sub,
                kind="expense",
            )
        )

    fid_disp = format_balance_display(fid, empty=empty_balance_copy)
    sav_disp = format_balance_display(sav, empty=empty_balance_copy)
    fid_cls = "pict-empty" if fid is None else ""
    sav_cls = "pict-empty" if sav is None else ""
    cards.append(
        _pict_card_html(
            emoji="📈",
            label="Brokerage / Fidelity",
            value_html=f'<span class="{fid_cls}">{fid_disp}</span>',
            sub=as_of_sub if fid is None else (f"as of {as_of}" if as_of else "Stored balance"),
            kind="brokerage",
        )
    )
    cards.append(
        _pict_card_html(
            emoji="🏦",
            label="Savings",
            value_html=f'<span class="{sav_cls}">{sav_disp}</span>',
            sub=as_of_sub if sav is None else (f"as of {as_of}" if as_of else "Stored balance"),
            kind="savings",
        )
    )

    if live_checking is not None or projected_month_end is not None:
        _live_sub = (
            f"as of {live_checking_as_of}"
            if live_checking_as_of
            else "Chase available today"
        )
        cards.append(
            _pict_card_html(
                emoji="💳",
                label="bank checking",
                value_html=_fmt_pict_money(live_checking, signed=None),
                sub=_live_sub,
                kind="brokerage",
            )
        )
        _proj_sub = projected_month_label or month_label or "Selected month"
        cards.append(
            _pict_card_html(
                emoji="📅",
                label="Projected month-end",
                value_html=_fmt_pict_money(projected_month_end, signed=None),
                sub=f"{_proj_sub} budget path",
                kind="savings",
            )
        )

    st.markdown(_pict_card_css(), unsafe_allow_html=True)
    st.markdown(
        '<div class="pict-row">' + "".join(cards) + "</div>",
        unsafe_allow_html=True,
    )




def _render_variable_amount_strip(conn, rules, actuals, settings) -> None:
    """Show variable essential forecast lines + Oct+ FPL/Water/Gas totals (partner-friendly)."""
    try:
        rows = variable_ui_rows(actuals or [], rules or [], as_of=date.today())
    except Exception:
        return
    if not rows:
        return

    st.markdown("##### Utility bills — planned amounts (from October on)")
    st.caption(
        "Due dates stay the same. September still follows your Excel plan (through Sep 30)."
    )

    for row in rows:
        cat = row.get("category") or ""
        fc = row.get("forecast")
        sentence = plain_english_variable_sentence(row)
        with st.container(border=True):
            st.markdown(_md(f"**{cat}** — Planning **{money(fc)}**"))
            st.markdown(_md(sentence))
            detail = plain_english_variable_detail_lines(row)
            if detail:
                with st.expander("More detail", expanded=False):
                    for line in detail:
                        st.caption(_md(line))

    try:
        totals = oct_plus_fpl_water_totals(
            rules or [],
            actuals or [],
            settings["start_date"],
            settings["end_date"],
            suppress_rules_through=settings.get("suppress_rules_through"),
        )
        end = totals.get("end")
        if isinstance(end, date):
            through_label = f"{month_name[end.month][:3]} {end.year}"
        else:
            through_label = str(end or "")
        new_s = money(totals.get("new_model"))
        old_s = money(totals.get("old_initiated"))
        delta = float(totals.get("delta") or 0)
        sign = "+" if delta >= 0 else "−"
        delta_s = f"{sign}${abs(delta):,.2f}"
        more_less = "more" if delta >= 0 else "less"
        start = totals.get("start")
        st.info(
            _md(
                f"**Through {through_label}:** planning FPL+Water+Gas this way totals about "
                f"**{new_s}**, vs **{old_s}** if we kept the old flat Excel stamps "
                f"(**{delta_s}** {more_less})."
            )
        )
        if start is not None and end is not None:
            st.caption(_md(f"Window: {start} → {end}"))
    except Exception:
        pass


def _render_forecast_coverage_panel(conn, daily, as_of, *, look_ahead_days: int = 90, rules=None, actuals=None, settings=None) -> None:
    """Compact coverage strip under the monthly income/expense cards."""
    findings = run_coverage_check(conn, daily, as_of, look_ahead_days=look_ahead_days)
    summary = summarize_coverage(findings)
    level = summary["level"]
    gaps = summary["gaps"]
    ok = summary["ok"]
    palette = {
        "green": ("#e8f8ef", "#1b6b3a", "#9ad4b0", "✅", "Forecast coverage looks complete"),
        "amber": ("#fff8e8", "#92400e", "#f3d19a", "⚠️", "Forecast coverage needs a look"),
        "red": ("#fdecec", "#9b2c2c", "#f0b4b4", "⛔", "Forecast coverage has gaps"),
    }
    bg, fg, border, emoji, headline = palette.get(level, palette["amber"])
    if level == "green":
        status = "All must-have bills and paychecks are on the next 90 days."
    elif level == "amber":
        n = len(gaps)
        status = f"{n} item{'s' if n != 1 else ''} look thin or off-amount in the next 90 days."
    else:
        n_miss = len(summary["missing"])
        n_weak = len(summary["weak"])
        bits = []
        if n_miss:
            bits.append(f"{n_miss} missing")
        if n_weak:
            bits.append(f"{n_weak} thin")
        status = f"{' · '.join(bits)} in the next 90 days — worth a quick look so nothing quietly drops off the plan."

    st.markdown(
        f"""
<div style="border-radius:14px;padding:0.85rem 1rem;margin:0.35rem 0 0.55rem;
background:linear-gradient(135deg,{bg} 0%,#fff 85%);border:1px solid {border};">
  <div style="display:flex;justify-content:space-between;gap:1rem;align-items:baseline;flex-wrap:wrap;">
    <div style="font-weight:750;color:{fg};font-size:1.05rem;">{emoji} {headline}</div>
    <div style="font-size:0.82rem;color:#6b7280;font-weight:650;">Next 90 days · as of {as_of.isoformat()}</div>
  </div>
  <div style="color:#3a4254;margin-top:0.25rem;">{status}</div>
</div>
        """,
        unsafe_allow_html=True,
    )
    st.caption(
        "This check watches must-have essentials (mortgage, utilities, cleaning, "
        "paychecks, savings extra) so a line cannot quietly disappear from the forecast. "
        "It also flags Chase history that looks monthly but is not projected. "
        "It does not change the income/expense totals above."
    )
    if rules is not None and settings is not None:
        _render_variable_amount_strip(conn, rules, actuals, settings)
    if gaps:
        for f in gaps:
            mark = "⛔" if f.get("severity") == "missing" else "⚠️"
            st.markdown(f"**{mark} {f.get('title') or f.get('name')}**")
            st.caption(_md(f.get("detail") or ""))
        prompts = gap_prompts(gaps)
        if prompts:
            with st.expander("Investigate prompts (copy for Chief of Staff)", expanded=False):
                st.caption("Plain language you can paste into a briefing or Slack.")
                st.code(prompts, language=None)
    if ok:
        with st.expander(f"Checked and present ({len(ok)})", expanded=False):
            for f in ok:
                st.markdown(f"**✅ {f.get('title') or f.get('name')}**")
                st.caption(_md(f.get("detail") or ""))



def flag_neg(n):
    return "🔴" if n and n > 0 else "🟢"


def _render_breach_autopsy(
    auto,
    *,
    key_prefix: str = "autopsy",
    mitigation=None,
    conn=None,
):
    """Render a breach autopsy block + optional Mitigation box (Dashboard / Month detail)."""
    if not auto:
        return
    st.markdown(f"**First red day:** {auto['first_breach']}")
    c1, c2, c3 = st.columns(3)
    c1.metric("EOD before", money(auto["prior_eod"]))
    c2.metric("EOD on breach", money(auto["breach_eod"]))
    c3.metric("Day flow sum", money(auto["flow_sum"]))
    st.write(auto["cause_summary"])
    flows_df = pd.DataFrame(
        [
            {
                "category": f["category"],
                "amount": f["amount"],
                "label": f.get("label") or "",
                "source": f.get("source") or "",
                "nature": category_nature(f["category"]) if f["amount"] < 0 else "",
            }
            for f in auto["flows"]
        ]
    )
    if not flows_df.empty:
        st.caption("Transactions that day (largest outflows first; nature = flexible/fixed)")
        st.dataframe(
            flows_df.style.format({"amount": "${:,.2f}"}),
            use_container_width=True,
            hide_index=True,
            key=f"{key_prefix}_flows_{auto['first_breach']}",
        )
    ni = auto.get("next_inflow")
    if ni:
        st.success(
            _md(
                f"Recovery: **{ni['category']}** {money(ni['amount'])} on "
                f"{ni['date']} → EOD {money(ni['eod'])}"
            )
        )
    else:
        st.caption("No subsequent inflow found in the projection window.")
    if auto.get("suggestion"):
        st.info(_md(auto["suggestion"]))

    if not mitigation:
        return

    # Detail only — Approve / Don't approve live on the Dashboard cards above.
    with st.expander("More detail — autopsy mitigations", expanded=False):
        base = mitigation.get("baseline") or {}
        st.caption(
            f"Baseline min balance {money(base.get('min_eod'))} · "
            f"{base.get('neg_days', 0)} red day(s). "
            "Use **Approve** on the card above to apply (month override only)."
        )
        if mitigation.get("note"):
            st.warning(mitigation["note"])

        rec = mitigation.get("recommended") or []
        if rec:
            bits = []
            for r in rec:
                sim = r.get("simulation") or {}
                clears = "would clear red" if sim.get("clears_first_breach") else "still red"
                bits.append(
                    f"**{r.get('summary')}** — {clears} / min {money(sim.get('new_min_eod'))}"
                )
            plan_clears = mitigation.get("plan_clears_breach")
            st.markdown(
                "Recommended: "
                + (" · ".join(bits))
                + (
                    f"  \n\nPlan: **{'would clear red' if plan_clears else 'still red'}** · "
                    f"min {money(mitigation.get('plan_min_eod'))}"
                )
            )
        else:
            st.caption("No applicable flexible/income-timing move in the recommended plan.")

        props = [p for p in (mitigation.get("proposals") or []) if p.get("kind") != "fixed_note"]
        fixed = [p for p in (mitigation.get("proposals") or []) if p.get("kind") == "fixed_note"]
        if props:
            st.markdown("**Ranked proposals**")
            for i, p in enumerate(props):
                sim = p.get("simulation") or {}
                clears = "would clear red" if sim.get("clears_first_breach") else "still red"
                st.markdown(
                    f"{i+1}. {p.get('summary')} — **{clears}** / min {money(sim.get('new_min_eod'))}"
                )
        if fixed:
            st.caption("Fixed (no skip): " + "; ".join(p["category"] for p in fixed))





def _render_top_mitigation_recommendations(
    *,
    conn,
    settings,
    rules,
    planned,
    actuals,
    res,
    months_all,
):
    """Simple Approve / Don't approve cards for open red months (partner-friendly)."""
    from calendar import month_abbr

    st.markdown("### Mitigation")
    st.caption("One card per open red month. Tap **Approve** to apply, or **Don't approve** to hide it.")

    applied = list_applied_mitigations(planned)
    red_months = [
        m
        for m in months_all
        if (m.get("days_negative") or 0) > 0 or m.get("first_breach")
    ]
    red_ym = {(m["year"], m["month"]) for m in red_months}
    clear_dismissed_if_not_red(red_ym)

    mit_cache = {}
    open_rows = []
    for m in red_months:
        auto = breach_autopsy(res["daily"], m["year"], m["month"])
        mit = None
        if auto:
            mit = mitigation_suggestions(
                res["daily"],
                m["year"],
                m["month"],
                start_date=settings["start_date"],
                end_date=settings["end_date"],
                start_balance=settings["start_balance"],
                rules=rules,
                planned=planned,
                actuals=actuals,
                warning_threshold=settings["warning_threshold"],
                suppress_rules_through=settings.get("suppress_rules_through"),
                autopsy=auto,
            )
        mit_cache[(m["year"], m["month"])] = (auto, mit)

        base_min = float(m.get("min_eod") or 0)
        rec = (mit or {}).get("recommended") or []
        clears = bool((mit or {}).get("plan_clears_breach")) if mit else False
        after_min = None
        plain = f"{m['label']}: red month — no simple fix yet"
        if rec:
            r0 = rec[0]
            after_min = ((r0.get("simulation") or {}).get("new_min_eod"))
            if after_min is None:
                after_min = (mit or {}).get("plan_min_eod")
            plain = plain_english_mitigation(
                category=r0.get("category") or "?",
                from_date=r0.get("from_date"),
                to_date=r0.get("suggested_to_date") or r0.get("from_date"),
                kind=r0.get("kind") or "move",
            )
            if len(rec) > 1:
                extras = " + ".join(
                    plain_english_mitigation(
                        category=r.get("category") or "?",
                        from_date=r.get("from_date"),
                        to_date=r.get("suggested_to_date") or r.get("from_date"),
                        kind=r.get("kind") or "move",
                    )
                    for r in rec[1:]
                )
                plain = f"{plain}; also {extras}"
        elif mit and mit.get("note"):
            plain = mit["note"]

        # Status text: only say cleared when simulation says so
        if clears:
            status_bit = "Would clear the red"
        elif rec:
            status_bit = "Helps, but month may still be red"
        else:
            status_bit = "Needs a closer look"

        open_rows.append(
            {
                "label": m["label"],
                "year": m["year"],
                "month": m["month"],
                "month_name": f"{month_abbr[m['month']]} {m['year']}",
                "plain": plain,
                "before_min": base_min,
                "after_min": after_min,
                "status_bit": status_bit,
                "clears": clears,
                "mit": mit,
                "dismissed": is_dismissed(m["year"], m["month"]),
            }
        )

    # Applied checklist (green) — only claim "cleared" when month is no longer red
    resolved_rows = [
        a for a in applied if (a["year"], a["month"]) not in red_ym
    ]
    still_red_applied = [
        a for a in applied if (a["year"], a["month"]) in red_ym
    ]

    if resolved_rows or still_red_applied:
        lines = []
        for a in resolved_rows:
            lines.append(f"✅ {applied_checklist_line(a)} (red cleared)")
        for a in still_red_applied:
            lines.append(f"✅ {applied_checklist_line(a)} (applied — month still red)")
        st.markdown("\n".join(lines))

    visible = [r for r in open_rows if not r["dismissed"]]
    skipped = [r for r in open_rows if r["dismissed"]]

    if not visible and not skipped and not resolved_rows and not still_red_applied:
        st.success("No open red months and no applied mitigations on the horizon.")
        return mit_cache

    if not visible and skipped:
        st.info("All open red-month cards were skipped. Expand a month below for detail, or undo a skip.")

    for row in visible:
        with st.container(border=True):
            st.markdown(f"### {row['month_name']}")
            st.markdown(f"**{row['plain']}**")
            before = money(row["before_min"])
            if row["after_min"] is not None:
                after = money(row["after_min"])
                st.caption(
                    f"Lowest balance: {before} → about {after}. {row['status_bit']}."
                )
            else:
                st.caption(f"Lowest balance now: {before}. {row['status_bit']}.")

            b1, b2 = st.columns(2)
            with b1:
                can_apply = bool(
                    row["mit"] and row["mit"].get("recommended_planned_items")
                )
                if st.button(
                    "Approve",
                    key=f"mit_approve_{row['year']}_{row['month']}",
                    type="primary",
                    use_container_width=True,
                    disabled=not can_apply,
                ):
                    ids = apply_mitigation_db(conn, row["mit"])
                    undismiss_month(row["year"], row["month"])
                    st.success(
                        f"Approved for {row['label']} ({len(ids)} planned row(s))."
                    )
                    rerun_clear()
            with b2:
                if st.button(
                    "Don't approve",
                    key=f"mit_skip_{row['year']}_{row['month']}",
                    use_container_width=True,
                ):
                    dismiss_month(row["year"], row["month"], reason="user")
                    st.info(f"Skipped {row['label']}.")
                    rerun_clear()

            with st.expander("More detail", expanded=False):
                mit = row["mit"]
                if mit:
                    rec = mit.get("recommended") or []
                    for r in rec:
                        sim = r.get("simulation") or {}
                        clears = sim.get("clears_first_breach")
                        st.markdown(
                            f"- {r.get('summary')} — "
                            f"{'would clear red' if clears else 'still red'} / "
                            f"min {money(sim.get('new_min_eod'))}"
                        )
                    props = [
                        p
                        for p in (mit.get("proposals") or [])
                        if p.get("kind") != "fixed_note"
                    ]
                    if props and (not rec or len(props) > len(rec)):
                        st.caption("Other ranked ideas")
                        for i, p in enumerate(props[:5]):
                            sim = p.get("simulation") or {}
                            st.markdown(
                                f"{i+1}. {p.get('summary')} — "
                                f"min {money(sim.get('new_min_eod'))}"
                            )
                    if mit.get("note"):
                        st.warning(mit["note"])
                else:
                    st.caption("No mitigation engine details for this month.")
                st.caption("Full day-by-day autopsy is under **What caused the red?** below.")

    if skipped:
        with st.expander(f"Skipped ({len(skipped)})", expanded=False):
            for row in skipped:
                c1, c2 = st.columns([4, 1])
                c1.markdown(f"🔇 **{row['month_name']}** — {row['plain']}")
                if c2.button("Undo", key=f"mit_undismiss_{row['year']}_{row['month']}"):
                    undismiss_month(row["year"], row["month"])
                    rerun_clear()

    st.caption(
        f"{len(visible)} open card(s) · {len(skipped)} skipped · "
        f"{len(resolved_rows) + len(still_red_applied)} applied."
    )
    return mit_cache





_BLACK_FRIENDLY_PARENT = {
    "Groceries": "Groceries",
    "Dining": "Eating out",
    "Transportation": "Gas & rides",
    "Shopping": "Shopping",
    "Health & Personal": "Kids, pets & personal",
    "School": "Kids & school",
    "Home Services & Subs": "Subscriptions & parks",
    "Entertainment": "Fun & outings",
    "Housing": "Home",
    "Auto": "Car",
    "Credit Cards": "Card payments",
    "Uncategorized": "Other",
    "Allowance": "Allowance",
    "Utilities": "Utilities",
    "Income": "Income",
    "Transfers / Savings": "Transfers",
    "Work Wash": "Work (reimbursed)",
}


def _friendly_parent(name: str) -> str:
    return _BLACK_FRIENDLY_PARENT.get(name or "", name or "Other")



def _render_suggested_cards(card_actuals):
    """Executive-simple Suggested cards module — live from chase_black_card actuals."""
    result = score_family_card_spend(card_actuals, exclude_one_offs=True, top_n=4)
    st.markdown("### Suggested cards for this spend")
    st.caption(
        _md(
            "Based on your family card purchases, here’s where points/cash stretch furthest."
        )
    )
    recs = result.get("recommendations") or []
    if not recs:
        st.info("Not enough family-card purchases yet to score cards.")
        return result

    chips = []
    for r in recs:
        net = float(r.get("net_value") or 0)
        signed = "pos" if net >= 0 else "neg"
        why = (r.get("why") or "")[:90]
        chips.append(
            _pict_card_html(
                emoji="💳",
                label=r.get("short_name") or r.get("name") or "Card",
                value_html=_fmt_pict_money(net, signed=signed),
                sub=why,
                kind="savings" if net >= 0 else "expense",
            )
        )
    st.markdown(_pict_card_css(), unsafe_allow_html=True)
    st.markdown('<div class="pict-row">' + "".join(chips) + "</div>", unsafe_allow_html=True)

    playbook = result.get("playbook") or []
    if playbook:
        st.markdown("**Pay with**")
        pdf = pd.DataFrame(
            [
                {
                    "Bucket": p.get("bucket_label") or p.get("bucket"),
                    "Best card": p.get("best_card"),
                    "Why": p.get("why"),
                }
                for p in playbook
            ]
        )
        st.dataframe(pdf, use_container_width=True, hide_index=True)

    refresh = format_refresh_line(result)
    one_off = ""
    excl = float(result.get("one_off_spend_excluded") or 0)
    if excl > 0:
        labs = ", ".join(result.get("one_off_labels") or []) or "auto dealers"
        one_off = (
            f" Typical-month scoring excludes one-offs (~{money(excl)}: {labs})."
        )
    st.caption(
        _md(
            f"{refresh}. "
            f"Rates as of {result.get('as_of_rates') or '—'}. "
            "Not advice — terms change. Costco often declines Amex. "
            "Recomputes from live chase_black_card actuals whenever you refresh or re-import the CSV "
            "(no frozen scores)."
            f"{one_off}"
        )
    )
    return result


def _black_card_rows(all_actuals):
    return [a for a in all_actuals if (a.get("source") or "") == BLACK_CARD_SOURCE]


def _render_black_card_import_box(conn, *, key_prefix: str):
    """Upload/replace Rewards Card card CSV. Never touches bank_csv."""
    uploaded = st.file_uploader(
        "Rewards Card card CSV",
        type=["csv"],
        key=f"{key_prefix}_upload",
        help="Transaction Date, Post Date, Description, Category, Type, Amount, Memo",
    )
    path_in = st.text_input(
        "Or path on server",
        value="",
        placeholder="/path/to/chase_black_card.csv",
        key=f"{key_prefix}_path",
    )
    if st.button("Import / replace Black card CSV", type="primary", key=f"{key_prefix}_run"):
        try:
            if uploaded is not None:
                import io
                raw = uploaded.getvalue().decode("utf-8-sig")
                report = import_black_card_csv(conn, io.StringIO(raw), replace=True)
            elif path_in.strip():
                report = import_black_card_csv(conn, path_in.strip(), replace=True)
            else:
                st.error("Provide a file upload or server path")
                report = None
            if report:
                st.success(
                    f"Imported {report['rows_imported']} Black card rows · "
                    f"{report['pct_categorized']}% categorized · "
                    f"did not touch bank_csv or due dates · "
                    f"Suggested cards will recompute from the new actuals"
                )
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("Rows", report["rows_imported"])
                c2.metric("Purchases", money(report["total_purchases"]))
                c3.metric("Payments", money(report["total_payments"]))
                c4.metric("Net", money(report["net"]))
                st.caption(_md(report.get("allowance_note") or ""))
                if report.get("top_categories_by_spend"):
                    st.dataframe(
                        pd.DataFrame(
                            report["top_categories_by_spend"],
                            columns=["category", "purchases"],
                        ),
                        use_container_width=True,
                        hide_index=True,
                    )
                st.cache_resource.clear()
        except Exception as e:
            st.error(f"Black card import failed: {e}")


def _compact_top_amt(amount):
    try:
        x = abs(float(amount or 0))
    except (TypeError, ValueError):
        return ""
    if abs(x - round(x)) < 1e-6:
        return f"−${int(round(x)):,}"
    return f"−${x:,.2f}"


def _spend_frame(actuals):
    """Debit actuals from bank_csv as a DataFrame with month / spend columns."""
    csv_actuals = [
        a for a in actuals
        if a.get("source") == CSV_SOURCE and float(a.get("amount") or 0) < 0
    ]
    if not csv_actuals:
        return pd.DataFrame()
    adf = pd.DataFrame(csv_actuals)
    adf["month"] = pd.to_datetime(adf["date"]).dt.to_period("M").astype(str)
    adf["spend"] = -adf["amount"].astype(float)
    adf["parent"] = adf["parent"].fillna("Uncategorized")
    adf["subcategory"] = adf["subcategory"].fillna("Uncategorized")
    adf["label"] = adf.get("label", pd.Series([""] * len(adf))).fillna("")
    return adf


def _mom_pivot(adf, *, parent=None, sub_order=None, n_months=12):
    """Month × subcategory spend pivot + MoM $ and % deltas for last two months."""
    if adf.empty:
        return None, None, None
    df = adf if parent is None else adf[adf["parent"] == parent]
    if df.empty:
        return None, None, None
    months = sorted(df["month"].unique())[-n_months:]
    df = df[df["month"].isin(months)]
    pivot = (
        df.groupby(["subcategory", "month"], as_index=False)["spend"]
        .sum()
        .pivot(index="subcategory", columns="month", values="spend")
        .fillna(0.0)
    )
    if sub_order:
        # Ensure locked taxonomy rows appear even when $0 in window
        for s in sub_order:
            if s not in pivot.index:
                pivot.loc[s] = 0.0
        ordered = [s for s in sub_order]
        rest = [s for s in pivot.index if s not in ordered]
        pivot = pivot.loc[ordered + rest]
    # totals row
    pivot.loc["TOTAL"] = pivot.sum(axis=0)
    # MoM vs prior complete-ish month (last two columns)
    mom = None
    if len(pivot.columns) >= 2:
        m_cur, m_prev = pivot.columns[-1], pivot.columns[-2]
        mom = pd.DataFrame({
            "subcategory": pivot.index,
            m_prev: pivot[m_prev].values,
            m_cur: pivot[m_cur].values,
        })
        mom["Δ $"] = mom[m_cur] - mom[m_prev]

        def _pct(r):
            if r[m_prev]:
                return f"{(r['Δ $'] / r[m_prev] * 100.0):+.0f}%"
            if r[m_cur] == 0:
                return "—"
            return "new"

        mom["Δ %"] = mom.apply(_pct, axis=1)
        mom = mom.set_index("subcategory")
    return pivot, mom, months



conn = get_conn()


def rerun_clear():
    st.cache_resource.clear()
    st.rerun()


# Sidebar nav
st.sidebar.title("Household Cashflow Engine")
page = st.sidebar.radio(
    "Pages",
    [
        "Household Cashflow Engine Dashboard",
        "Household monthly operating income & expenses",
        "Household spending & income insights",
        "Rewards Card — demo rewards card",
        "Household debt paydown",
        "Retirement runway",
        "Rules",
        "Month detail",
        "Scenarios",
        "Import",
        "Settings",
    ],
    label_visibility="collapsed",
)

settings = db.get_settings(conn)
rules = db.list_rules(conn)
planned = db.list_planned(conn)
all_actuals = db.list_actuals(conn)
# Card activity is a separate folder — never fold into checking cash twin.
actuals = [a for a in all_actuals if (a.get("source") or "") != BLACK_CARD_SOURCE]
scenarios = db.list_scenarios(conn)

st.sidebar.caption(
    _md(
        f"Horizon {settings['start_date']} → {settings['end_date']}\n\n"
        f"Start bal {money(settings['start_balance'])} · warn < {money(settings['warning_threshold'])}"
    )
)

# ---------- DASHBOARD ----------
if page == "Household Cashflow Engine Dashboard":
    st.title("Household Cashflow Engine Dashboard")
    st.caption(
        "Baseline projection from seed rules + paychecks. "
        "Lead with months that go negative; full 3-year detail is below."
    )

    res = project(
        settings["start_date"],
        settings["end_date"],
        settings["start_balance"],
        rules,
        planned,
        actuals,
        None,
        settings["warning_threshold"],
        suppress_rules_through=settings.get("suppress_rules_through"),
    )
    s = res["summary"]
    months_all = res["months"]
    years_present = sorted({int(m["year"]) for m in months_all})

    # Year filter options + session default (needed before scorecard click buttons)
    year_options = [str(y) for y in years_present] + ["All"]
    _today_y = date.today().year
    default_year = str(_today_y) if str(_today_y) in year_options else (
        str(years_present[0]) if years_present else "All"
    )
    if "dash_year_filter" not in st.session_state:
        st.session_state.dash_year_filter = default_year
    elif st.session_state.dash_year_filter not in year_options:
        st.session_state.dash_year_filter = default_year

    # --- Year pitfall scorecard (horizon) ---
    _render_year_pitfall_scorecard(
        months_all,
        years_present,
        warning_threshold=settings["warning_threshold"],
    )

    # --- Cash cushion / red-streak executive card ---
    _render_red_streak_cushion_card(months_all)

    # --- Mitigation recommendations (top) ---
    mit_cache = _render_top_mitigation_recommendations(
        conn=conn,
        settings=settings,
        rules=rules,
        planned=planned,
        actuals=actuals,
        res=res,
        months_all=months_all,
    )

    # --- Pictorial summary cards (this month + net-worth placeholders) ---
    _today = date.today()
    _dash_ym = (_today.year, _today.month)
    _avail_months = available_calendar_months(res["daily"])
    if _dash_ym not in _avail_months:
        _start = settings["start_date"]
        _dash_ym = (_start.year, _start.month)
        if _dash_ym not in _avail_months and _avail_months:
            _dash_ym = _avail_months[0]
    _dash_totals = {"money_in": 0.0, "money_out": 0.0}
    if _avail_months:
        _cl = month_bill_checklist(res["daily"], _dash_ym[0], _dash_ym[1])
        _dash_totals = month_money_totals(_cl)
    _dash_label = f"{month_name[_dash_ym[1]]} {_dash_ym[0]}"
    # Live bank vs budgeted month-end (two different checkpoints)
    _live_bal = None
    _live_row = conn.execute(
        "SELECT value FROM settings WHERE key='live_checking_balance'"
    ).fetchone()
    if _live_row and _live_row[0] not in (None, ""):
        try:
            _live_bal = float(_live_row[0])
        except ValueError:
            _live_bal = None
    _sep_me = next((m["month_end"] for m in months_all if m["label"] == "2026-09"), None)
    _lc1, _lc2, _lc3 = st.columns(3)
    _lc1.metric(
        "Live checking (today)",
        money(_live_bal) if _live_bal is not None else "—",
        help="Chase available balance as of latest screenshot — not the projection start.",
    )
    _lc2.metric(
        "Budget Sep month-end",
        money(_sep_me) if _sep_me is not None else "—",
        help="Forecast month-end from the Budget workbook path (incl. \\$50 Chase adj).",
    )
    _lc3.metric(
        "Projection start",
        money(settings["start_balance"]),
        help="Cash used to run the Sep bridge so month-end can tie to budget.",
    )
    st.caption(
        "Today’s bank and September’s budgeted ending are different checkpoints: "
        "live cash is what you have now; Sep month-end is where the plan lands after remaining September bills."
    )

    st.markdown("### At a glance")
    _render_summary_icon_cards(
        money_in=_dash_totals.get("money_in"),
        money_out=_dash_totals.get("money_out"),
        include_flow=True,
        month_label=_dash_label,
        snapshot=load_snapshot(),
        empty_balance_copy="—",
    )

    # --- Year filter ---
    sel = st.selectbox(
        "Year filter",
        year_options,
        help="Scorecard below shows one row per month for the selected year (or all). "
        "Tip: tap a year card above to jump here.",
        key="dash_year_filter",
    )
    sel_year = None if sel == "All" else int(sel)
    months_view = filter_months_for_year(months_all, sel_year)
    kpis = year_scorecard_kpis(months_view)

    # --- Primary KPIs for selection (not horizon ending balance) ---
    scope = sel if sel != "All" else "horizon"
    c1, c2, c3, c4 = st.columns(4)
    c1.metric(f"Min EOD ({scope})", money(kpis["min_eod"]))
    c2.metric(f"Red months ({scope})", kpis["red_months"])
    c3.metric(f"Neg days ({scope})", kpis["negative_days"])
    c4.metric("First breach", str(kpis["first_breach"] or "None"))

    def _month_rows(month_list):
        rows = []
        for m in month_list:
            rows.append(
                {
                    "Month": m["label"],
                    "Month-end": m["month_end"],
                    "Days < $0": m["days_negative"],
                    "Days < warn": m["days_warning"],
                    "Min EOD": m["min_eod"],
                    "First breach": m["first_breach"].isoformat() if m["first_breach"] else "",
                    "Flag": flag_neg(m["days_negative"]),
                }
            )
        return pd.DataFrame(rows)

    def style_row(row):
        if row["Days < $0"] > 0:
            return ["background-color: #ffcccc"] * len(row)
        if row["Days < warn"] > 0:
            return ["background-color: #fff3cd"] * len(row)
        return ["background-color: #d4edda"] * len(row)

    # --- Monthly scorecard (selected year) ---
    st.subheader(f"Monthly scorecard — {sel}")
    st.caption("Excel Summary-style: one row per month-end with breach flags.")
    df_year = _month_rows(months_view)
    score_height = min(420, 38 + 35 * max(len(df_year), 1))
    st.dataframe(
        df_year.style.apply(style_row, axis=1).format(
            {"Month-end": "${:,.2f}", "Min EOD": "${:,.2f}"}
        ),
        use_container_width=True,
        height=score_height,
    )

    # --- Breach autopsy for red months in selected year ---
    red_months = [
        m for m in months_view if (m.get("days_negative") or 0) > 0 or m.get("first_breach")
    ]
    if red_months:
        st.subheader("What caused the red?")
        st.caption(
            "Pinpoint the first negative day so you can move flexible expenses "
            "or request Jordan pay earlier."
        )
        for m in red_months:
            cached = mit_cache.get((m["year"], m["month"])) if mit_cache else None
            if cached:
                auto, mit = cached
            else:
                auto = breach_autopsy(res["daily"], m["year"], m["month"])
                mit = None
                if auto:
                    mit = mitigation_suggestions(
                        res["daily"],
                        m["year"],
                        m["month"],
                        start_date=settings["start_date"],
                        end_date=settings["end_date"],
                        start_balance=settings["start_balance"],
                        rules=rules,
                        planned=planned,
                        actuals=actuals,
                        warning_threshold=settings["warning_threshold"],
                        suppress_rules_through=settings.get("suppress_rules_through"),
                        autopsy=auto,
                    )
            title = f"What caused the red? — {m['label']}"
            if auto:
                title += f" ({auto['first_breach']})"
            with st.expander(title, expanded=(len(red_months) == 1)):
                if auto:
                    _render_breach_autopsy(
                        auto,
                        key_prefix=f"dash_{m['label']}",
                        mitigation=mit,
                        conn=conn,
                    )
                else:
                    st.write("No breach detail available.")

    # --- Variable amounts (CONVERGE C) near 3-year view ---
    _render_variable_amount_strip(conn, rules, actuals, settings)

    # --- Full 3-year table (secondary) ---
    with st.expander("Full 3-year month-end table", expanded=False):
        df_all = _month_rows(months_all)
        st.dataframe(
            df_all.style.apply(style_row, axis=1).format(
                {"Month-end": "${:,.2f}", "Min EOD": "${:,.2f}"}
            ),
            use_container_width=True,
            height=560,
        )

    st.subheader("Year summaries")
    ydf = pd.DataFrame(
        [
            {
                "Year": y["year"],
                "Ending": y["ending_balance"],
                "Min EOD": y["min_eod"],
                "Neg days": y["negative_days"],
                "Red months": y["red_months"],
                "First breach": y["first_breach"].isoformat() if y["first_breach"] else "",
            }
            for y in res["years"]
        ]
    )
    st.dataframe(
        ydf.style.format({"Ending": "${:,.2f}", "Min EOD": "${:,.2f}"}),
        use_container_width=True,
    )

    st.caption(
        "Spend mix, MoM trends, and income dependency live on "
        "**Household spending & income insights**."
    )


# ---------- BILLS (checklist playbook) ----------
elif page == "Household monthly operating income & expenses":
    st.title("Household monthly operating income & expenses")
    st.caption(
        "Income first, then bills by week. "
        "**Must pay** = mortgage, utilities, insurance, loans, tuition (no luxury to skip). "
        "**Flexible** = Savings, allowance, discretionary (move at your discretion). "
        "Memberships tagged separately. Dashboard still owns red-month health checks."
    )

    res = project(
        settings["start_date"],
        settings["end_date"],
        settings["start_balance"],
        rules,
        planned,
        actuals,
        None,
        settings["warning_threshold"],
        suppress_rules_through=settings.get("suppress_rules_through"),
    )
    months = available_calendar_months(res["daily"])
    if not months:
        st.warning("No projection days in horizon.")
        st.stop()

    start = settings["start_date"]
    default_ym = (start.year, start.month)
    if default_ym not in months:
        default_ym = months[0]

    labels = [f"{y}-{m:02d}" for y, m in months]
    default_label = f"{default_ym[0]}-{default_ym[1]:02d}"
    if "cal_month_select" not in st.session_state or st.session_state.cal_month_select not in labels:
        st.session_state.cal_month_select = default_label

    cur_label = st.session_state.cal_month_select
    cur_idx = labels.index(cur_label)

    c_prev, c_pick, c_next = st.columns([1, 3, 1])
    with c_prev:
        if st.button("← Prev", use_container_width=True, key="cal_prev", disabled=cur_idx <= 0):
            st.session_state.cal_month_select = labels[cur_idx - 1]
            st.rerun()
    with c_next:
        if st.button("Next →", use_container_width=True, key="cal_next", disabled=cur_idx >= len(labels) - 1):
            st.session_state.cal_month_select = labels[cur_idx + 1]
            st.rerun()
    with c_pick:
        st.selectbox(
            "Month",
            labels,
            key="cal_month_select",
            label_visibility="collapsed",
        )

    yy, mm = map(int, st.session_state.cal_month_select.split("-"))
    st.subheader(f"{month_name[mm]} {yy}")

    checklist = month_bill_checklist(res["daily"], yy, mm)
    income_rows, bill_rows = split_month_checklist(checklist)
    totals = month_money_totals(checklist)
    by_date = month_days_index(res["daily"], yy, mm)
    week_sections = week_playbook_sections(checklist, yy, mm)
    bill_parts = bifurcate_bill_rows(bill_rows)

    # Pictorial summary: income / expenses / balances + Chase + projected month-end
    _live_bal = None
    _live_as_of = None
    _live_row = conn.execute(
        "SELECT value FROM settings WHERE key='live_checking_balance'"
    ).fetchone()
    if _live_row and _live_row[0] not in (None, ""):
        try:
            _live_bal = float(_live_row[0])
        except ValueError:
            _live_bal = None
    _asof_row = conn.execute(
        "SELECT value FROM settings WHERE key='live_checking_as_of'"
    ).fetchone()
    if _asof_row and _asof_row[0] not in (None, ""):
        _live_as_of = str(_asof_row[0])
    else:
        try:
            _lj = json.loads((Path(__file__).resolve().parent / "data" / "live_checking.json").read_text())
            if _live_bal is None and _lj.get("balance") is not None:
                _live_bal = float(_lj["balance"])
            _live_as_of = _live_as_of or _lj.get("as_of")
        except Exception:
            pass

    _ym_label = f"{yy}-{mm:02d}"
    _proj_me = next(
        (m["month_end"] for m in res["months"] if m.get("label") == _ym_label),
        None,
    )

    _render_summary_icon_cards(
        money_in=totals.get("money_in"),
        money_out=totals.get("money_out"),
        include_flow=True,
        month_label=f"{month_name[mm]} {yy}",
        snapshot=load_snapshot(),
        empty_balance_copy="—",
        live_checking=_live_bal,
        live_checking_as_of=_live_as_of,
        projected_month_end=_proj_me,
        projected_month_label=f"{month_name[mm]} {yy}",
    )
    st.caption(
        "**Income this month** and **Household expenses** are that selected month’s totals "
        "from the checklist below (same lines, same sum). "
        "**bank checking** is today’s available balance (pending already in that number). "
        "**Projected month-end** is the budget-path ending for the month you selected. "
        "Expenses include Savings transfers and allowance; "
        "Rewards Card card spend is excluded (separate ledger). "
        "September 2026 uses Budget workbook planned stamps with rules suppressed through Sep 30."
    )

    _cov_as_of = date.today()
    if _cov_as_of < settings["start_date"]:
        _cov_as_of = settings["start_date"]
    _render_forecast_coverage_panel(conn, res["daily"], _cov_as_of, rules=rules, actuals=actuals, settings=settings)

    TYPE_EMOJI = {
        "income": "🟢",
        "fixed": "⬜",
        "flexible": "🔶",
        "membership": "💜",
    }
    TYPE_HINT = {
        "fixed": "must pay",
        "flexible": "flexible",
        "membership": "membership",
        "income": "income",
    }

    def _fmt_item_row(r: dict) -> str:
        typ = type_display_label(r["bucket"], r.get("nature") or "")
        emoji = TYPE_EMOJI.get(typ, "▪️")
        hint = TYPE_HINT.get(typ, typ)
        moved_badge = " · <b style='color:#b45309;'>↪️ moved</b>" if r.get("moved") else ""
        amt = float(r["amount"])
        amt_s = f"+${amt:,.2f}" if amt >= 0 else f"−${abs(amt):,.2f}"
        color = "#1b6b3a" if amt >= 0 else "#3a4254"
        bg = "#eefaf2" if amt >= 0 else "#fff"
        border = "#b7e0c5" if amt >= 0 else "#edf0f5"
        return (
            f"<div style='display:flex;justify-content:space-between;gap:1rem;"
            f"padding:0.4rem 0.55rem;margin:0.15rem 0;border-radius:10px;"
            f"background:{bg};border:1px solid {border};'>"
            f"<div>{emoji} <b>{r['category']}</b>"
            f"<span style='color:#6b7280;font-size:0.85rem;'> · {hint}</span>"
            f"{moved_badge}</div>"
            f"<div style='font-weight:700;color:{color};white-space:nowrap;'>{amt_s}</div>"
            f"</div>"
        )

    st.markdown(
        """
<style>
.bills-legend {
  display: flex; flex-wrap: wrap; gap: 0.55rem 1.1rem; align-items: center;
  margin: 0.15rem 0 0.75rem 0; font-size: 0.9rem; color: #3a4254;
}
.bills-week-meta { color: #6b7280; font-size: 0.88rem; margin: 0 0 0.4rem 0; }
.bills-day-head { font-weight: 650; color: #2c3340; margin: 0.55rem 0 0.2rem 0; }
.bills-sublabel {
  font-size: 0.78rem; font-weight: 650; text-transform: uppercase;
  letter-spacing: 0.04em; color: #6b7280; margin: 0.35rem 0 0.1rem 0.1rem;
}
.bills-income-card {
  border-radius: 14px; padding: 0.85rem 1rem; margin: 0.25rem 0 0.85rem;
  background: linear-gradient(135deg, #e8f8ef 0%, #f4fcf7 100%);
  border: 1px solid #9ad4b0;
}
</style>
        """,
        unsafe_allow_html=True,
    )

    st.markdown(
        '<div class="bills-legend">'
        "<span>🟢 Income / payday</span>"
        "<span>⬜ <b>Must pay</b> (fixed)</span>"
        "<span>🔶 <b>Flexible</b></span>"
        "<span>💜 Membership</span>"
        "<span>↪️ <b>moved</b> (mitigation)</span>"
        "</div>",
        unsafe_allow_html=True,
    )

    # ----- 1) Income this month (clear separate section) -----
    st.markdown("### 💵 Income this month")
    if not income_rows:
        st.info("No income lines projected this month.")
    else:
        st.markdown(
            f'<div class="bills-income-card">'
            f"<b>{len(income_rows)}</b> paycheck / income line(s) · "
            f"total <b style='color:#1b6b3a;'>+\\${totals['money_in']:,.2f}</b>"
            f"</div>",
            unsafe_allow_html=True,
        )
        inc_df = pd.DataFrame(
            [
                {
                    "Date": f"{r['weekday']} {r['day']}",
                    "Name": r["category"],
                    "Amount": r["amount"],
                    "Notes": ("↪️ moved" if r.get("moved") else "")
                    or (r.get("notes") or ""),
                }
                for r in income_rows
            ]
        )
        st.dataframe(
            inc_df.style.format({"Amount": "${:,.2f}"}),
            use_container_width=True,
            hide_index=True,
        )

    # ----- 2) Bills by week (primary checklist) -----
    st.markdown("### 🏠 Bills by week")
    n_must = len(bill_parts["must_pay"])
    n_flex = len(bill_parts["flexible"])
    n_mem = len(bill_parts["membership"])
    st.caption(
        f"{len(bill_rows)} bill(s) this month · "
        f"must pay {n_must} · flexible {n_flex} · membership {n_mem}"
        + (f" · {totals['moved_count']} moved" if totals["moved_count"] else "")
        + f" · total out \\${totals['money_out']:,.2f}"
    )

    active_weeks = [sec for sec in week_sections if sec["days"]]
    if not active_weeks:
        st.info("No projected income or bills this month.")
    else:
        for sec in active_weeks:
            title = f"{sec['label']} · {sec['item_count']} item(s)"
            with st.expander(title, expanded=True):
                st.markdown(
                    f'<p class="bills-week-meta">'
                    f"{sec['income_count']} income · {sec['bill_count']} bill(s)"
                    f" · {sec['start'].strftime('%b')} {sec['start'].day}–{sec['end'].day}"
                    f"</p>",
                    unsafe_allow_html=True,
                )
                for day in sec["days"]:
                    d = day["date"]
                    st.markdown(
                        f'<div class="bills-day-head">{day["weekday"]} {day["day"]}</div>',
                        unsafe_allow_html=True,
                    )
                    # Show income on the day (pay / other income), then bifurcated bills
                    if day["income"]:
                        st.markdown(
                            '<div class="bills-sublabel">Pay / income</div>',
                            unsafe_allow_html=True,
                        )
                        st.markdown(
                            "".join(_fmt_item_row(r) for r in day["income"]),
                            unsafe_allow_html=True,
                        )
                    if day["must_pay"]:
                        st.markdown(
                            '<div class="bills-sublabel">Must pay (fixed)</div>',
                            unsafe_allow_html=True,
                        )
                        st.markdown(
                            "".join(_fmt_item_row(r) for r in day["must_pay"]),
                            unsafe_allow_html=True,
                        )
                    if day["flexible"]:
                        st.markdown(
                            '<div class="bills-sublabel">Flexible</div>',
                            unsafe_allow_html=True,
                        )
                        st.markdown(
                            "".join(_fmt_item_row(r) for r in day["flexible"]),
                            unsafe_allow_html=True,
                        )
                    if day["membership"]:
                        st.markdown(
                            '<div class="bills-sublabel">Memberships</div>',
                            unsafe_allow_html=True,
                        )
                        st.markdown(
                            "".join(_fmt_item_row(r) for r in day["membership"]),
                            unsafe_allow_html=True,
                        )
                    if day["other"]:
                        st.markdown(
                            '<div class="bills-sublabel">Other</div>',
                            unsafe_allow_html=True,
                        )
                        st.markdown(
                            "".join(_fmt_item_row(r) for r in day["other"]),
                            unsafe_allow_html=True,
                        )
                    row = by_date.get(d)
                    if row:
                        flag = (
                            "🔴 red"
                            if row.get("negative")
                            else ("🟡 warn" if row.get("warning") else "🟢 ok")
                        )
                        st.caption(
                            f"Day flow {money(row['flow_sum'])} · EOD {money(row['eod'])} · {flag}"
                        )

    # ----- 3) Optional tiny visual map (demoted, collapsed) -----
    with st.expander("Optional visual map (week timing)", expanded=False):
        st.caption(
            "Tiny timing map only — not the main view. "
            "🟢 income · ⬜ fixed · 🔶 flexible · 💜 membership · ↪️ moved"
        )
        lanes = month_week_lanes(yy, mm)
        day_chips = {d: effective_day_flows(row.get("flows") or []) for d, row in by_date.items()}

        def _mini_pills(chips: list) -> str:
            if not chips:
                return "·"
            counts = pill_bucket_counts(chips)
            bits = (
                ["🟢"] * counts[BUCKET_INCOME]
                + ["⬜"] * counts[BUCKET_FIXED]
                + ["🔶"] * counts[BUCKET_FLEXIBLE]
                + ["💜"] * counts[BUCKET_LIFESTYLE]
                + ["▪️"] * counts[BUCKET_OTHER]
            )
            body = "".join(bits[:5])
            if len(bits) > 5:
                body += f"+{len(bits) - 5}"
            if counts["moved"]:
                body += f" ↪️{counts['moved']}"
            return body

        hdr = st.columns(8)
        hdr[0].markdown("**W**")
        for i, h in enumerate(["Su", "Mo", "Tu", "We", "Th", "Fr", "Sa"]):
            hdr[i + 1].markdown(f"**{h}**")
        for lane in lanes:
            cols = st.columns(8)
            cols[0].caption(f"W{lane['week_index'] + 1}")
            for ci, cell in enumerate(lane["days"]):
                with cols[ci + 1]:
                    if cell is None or cell not in by_date:
                        st.caption("·")
                    else:
                        chips = day_chips.get(cell) or []
                        st.caption(f"{cell.day} {_mini_pills(chips)}")

    with st.expander("Full month table (income + bills)", expanded=False):
        if not checklist:
            st.info("No projected items this month.")
        else:
            full_df = pd.DataFrame(
                [
                    {
                        "Day": f"{r['weekday']} {r['day']}",
                        "Name": r["category"],
                        "Amount": r["amount"],
                        "Type": type_display_label(r["bucket"], r.get("nature") or ""),
                        "Moved": "↪️ moved" if r.get("moved") else "",
                    }
                    for r in checklist
                ]
            )
            st.dataframe(
                full_df.style.format({"Amount": "${:,.2f}"}),
                use_container_width=True,
                hide_index=True,
                height=min(560, 80 + 35 * min(len(full_df), 16)),
            )


# ---------- INSIGHTS (income + spend analytics) ----------
elif page == "Household spending & income insights":
    st.title("Household spending & income insights")
    st.caption(
        "Pictures first — can Alex's income carry the household? "
        "Bank CSV actuals for this year vs last year; projection only in a collapsed forecast. "
        "Dashboard = runway; Bills = monthly playbook."
    )

    res = project(
        settings["start_date"],
        settings["end_date"],
        settings["start_balance"],
        rules,
        planned,
        actuals,
        None,
        settings["warning_threshold"],
        suppress_rules_through=settings.get("suppress_rules_through"),
    )

    # ----- Income section -----
    st.markdown("## Income")

    act_inc = insights_eng.income_frame_from_actuals(actuals)
    last_actual_d = None
    if not act_inc.empty:
        last_actual_d = max(act_inc["date"])
    else:
        last_actual_d = settings["start_date"] - timedelta(days=1)
    fc_inc = insights_eng.income_frame_from_projection(res["daily"], after=last_actual_d)
    idf = insights_eng.combine_income_history_forecast(act_inc, fc_inc)
    monthly_inc = insights_eng.monthly_income_by_stream(idf)

    as_of = date.today()
    this_year = as_of.year
    last_year = this_year - 1

    if monthly_inc.empty:
        st.info("No income streams yet — import bank CSV or check paycheck rules.")
    else:
        # Focus: actuals for this calendar year (YTD) for cards + %
        ytd_streams = insights_eng.annual_income_by_stream(idf, this_year, origin="actual")
        ytd_total = float(ytd_streams["amount"].sum()) if not ytd_streams.empty else 0.0

        card_meta = [
            (STREAM_PRIMARY, "💼", "Alex (Northstar Tech)"),
            (STREAM_SECONDARY, "💜", "Jordan paycheck"),
            (STREAM_SIDE_GIG, "🏫", "Side gig / secondary"),
            (STREAM_OTHER, "🎁", "Other / gifts"),
        ]
        st.markdown(_pict_card_css(), unsafe_allow_html=True)
        cards_html = ['<div class="pict-row">']
        for stream, emoji, title in card_meta:
            row = ytd_streams[ytd_streams["stream"] == stream] if not ytd_streams.empty else None
            amt = float(row["amount"].iloc[0]) if row is not None and len(row) else 0.0
            pct = (100.0 * amt / ytd_total) if ytd_total > 0 else 0.0
            cards_html.append(
                _pict_card_html(
                    emoji=emoji,
                    label=title,
                    value_html=f'<span class="pict-pos">${amt:,.0f}</span>',
                    sub=f"{pct:.0f}% of {this_year} income · YTD",
                    kind="income",
                )
            )
        cards_html.append("</div>")
        st.markdown("".join(cards_html), unsafe_allow_html=True)
        st.caption(
            _md(
                f"Goal: Alex carries the household; Jordan off operating cash by 2028. "
                f"({GOAL_NARRATIVE})"
            )
        )

        mix = insights_eng.income_mix_with_labels(insights_eng.income_mix_latest(monthly_inc))
        mix_month = mix["month"].iloc[0] if not mix.empty else None
        mix_label = insights_eng.month_key_label(mix_month) if mix_month else "—"

        st.markdown(f"#### Income mix — {mix_label}")
        if mix.empty:
            st.write("No mix for latest month.")
        else:
            _mix_origin = (
                monthly_inc.loc[mix_month, "origin"]
                if mix_month and "origin" in monthly_inc.columns and mix_month in monthly_inc.index
                else "actual"
            )
            st.caption(
                f"Latest {_mix_origin} month · labels show \\$ and % of that month."
            )
            try:
                import altair as alt

                donut = (
                    alt.Chart(mix)
                    .mark_arc(innerRadius=50)
                    .encode(
                        theta=alt.Theta("amount:Q", stack=True),
                        color=alt.Color(
                            "label:N",
                            title="Stream",
                            sort=list(mix["label"]),
                            legend=alt.Legend(labelLimit=280),
                        ),
                        tooltip=[
                            alt.Tooltip("short:N", title="Stream"),
                            alt.Tooltip("amount:Q", format="$,.0f", title="$"),
                            alt.Tooltip("pct:Q", format=".0f", title="%"),
                        ],
                    )
                    .properties(height=300)
                )
                # Side bar with same labels for readability
                bars = (
                    alt.Chart(mix)
                    .mark_bar()
                    .encode(
                        y=alt.Y("short:N", sort="-x", title=None),
                        x=alt.X("amount:Q", title="Income ($)"),
                        color=alt.Color("label:N", legend=None),
                        tooltip=[
                            "short",
                            alt.Tooltip("amount:Q", format="$,.0f"),
                            alt.Tooltip("pct:Q", format=".0f", title="%"),
                        ],
                    )
                )
                text = (
                    alt.Chart(mix)
                    .mark_text(align="left", dx=4)
                    .encode(
                        y=alt.Y("short:N", sort="-x"),
                        x=alt.X("amount:Q"),
                        text=alt.Text("label:N"),
                    )
                )
                c_donut, c_bar = st.columns([1, 1.15])
                with c_donut:
                    st.altair_chart(donut, use_container_width=True)
                with c_bar:
                    st.altair_chart((bars + text).properties(height=280), use_container_width=True)
            except Exception:
                _mix_fb = mix[["short", "amount"]].copy()
                labeled_bars(_mix_fb, x_col="short", y_col="amount", horizontal=True, height=280)

        # This year vs last year (actuals) — not a 36-month forecast blob
        st.markdown(f"#### This year vs last year ({this_year} vs {last_year})")
        yoy = insights_eng.income_yoy_comparison(
            idf, this_year, last_year, as_of=as_of, origin="actual"
        )
        if yoy.empty or float(yoy[["last_year", "this_ytd"]].to_numpy().sum()) <= 0:
            st.write("Need actuals in both years for a comparison.")
        else:
            try:
                import altair as alt

                long_yoy = []
                for _, r in yoy.iterrows():
                    long_yoy.append(
                        {
                            "short": r["short"],
                            "period": str(last_year),
                            "amount": float(r["last_year"]),
                        }
                    )
                    long_yoy.append(
                        {
                            "short": r["short"],
                            "period": f"{this_year} YTD",
                            "amount": float(r["this_ytd"]),
                        }
                    )
                yoy_df = pd.DataFrame(long_yoy)
                # % within each period for labels
                for period in yoy_df["period"].unique():
                    mask = yoy_df["period"] == period
                    tot = float(yoy_df.loc[mask, "amount"].sum())
                    yoy_df.loc[mask, "pct"] = (
                        100.0 * yoy_df.loc[mask, "amount"] / tot if tot > 0 else 0.0
                    )
                yoy_df["label"] = [
                    f"${r['amount']:,.0f} ({r['pct']:.0f}%)" for _, r in yoy_df.iterrows()
                ]
                grouped = (
                    alt.Chart(yoy_df)
                    .mark_bar()
                    .encode(
                        x=alt.X("short:N", title=None, sort=[STREAM_SHORT[s] for s in STREAM_ORDER]),
                        xOffset="period:N",
                        y=alt.Y("amount:Q", title="Income ($)"),
                        color=alt.Color("period:N", title="Period"),
                        tooltip=[
                            "short",
                            "period",
                            alt.Tooltip("amount:Q", format="$,.0f"),
                            alt.Tooltip("pct:Q", format=".0f", title="% of period"),
                        ],
                    )
                )
                labels = (
                    alt.Chart(yoy_df)
                    .mark_text(dy=-8, fontSize=11)
                    .encode(
                        x=alt.X("short:N", sort=[STREAM_SHORT[s] for s in STREAM_ORDER]),
                        xOffset="period:N",
                        y=alt.Y("amount:Q"),
                        text=alt.Text("label:N"),
                        color=alt.value("#374151"),
                    )
                )
                st.altair_chart(
                    (grouped + labels).properties(height=320),
                    use_container_width=True,
                )
            except Exception:
                plot = yoy.set_index("short")[["last_year", "this_ytd"]].rename(
                    columns={"last_year": str(last_year), "this_ytd": f"{this_year} YTD"}
                )
                _yoy_long = (
                    plot.reset_index()
                    .melt(id_vars="short", var_name="period", value_name="amount")
                )
                labeled_bars(
                    _yoy_long,
                    x_col="short",
                    y_col="amount",
                    color_col="period",
                    height=300,
                    x_sort=[STREAM_SHORT[s] for s in STREAM_ORDER if STREAM_SHORT[s] in plot.index],
                    color_domain=[str(last_year), f"{this_year} YTD"],
                )
            st.caption(
                f"{last_year} = full-year actuals present in CSV · "
                f"{this_year} YTD through {insights_eng.month_key_label(as_of.strftime('%Y-%m'))}."
            )

        with st.expander("Month-by-month (last 12)", expanded=False):
            show_m = list(monthly_inc.index)[-12:]
            plot = monthly_inc.loc[show_m, STREAM_ORDER].copy()
            plot.columns = [STREAM_SHORT.get(c, c) for c in plot.columns]
            long_m = (
                plot.reset_index()
                .melt(id_vars="month", var_name="stream", value_name="amount")
            )
            labeled_bars(
                long_m,
                x_col="month",
                y_col="amount",
                color_col="stream",
                height=280,
                x_sort=show_m,
                color_domain=[STREAM_SHORT[s] for s in STREAM_ORDER],
                stack="zero",
            )
            origins = monthly_inc.loc[show_m, "origin"] if "origin" in monthly_inc.columns else None
            if origins is not None:
                n_act = int((origins == "actual").sum())
                n_fc = int((origins == "forecast").sum())
                st.caption(
                    f"{show_m[0]} → {show_m[-1]} · {n_act} actual, {n_fc} forecast month(s)."
                )

        # Annual stream totals — calendar years + run-rate (NOT multi-year lump)
        st.markdown("#### Annual stream totals")
        ann_tbl = yoy[["short", "last_year", "this_ytd", "this_run_rate"]].copy()
        ann_tbl = ann_tbl.rename(
            columns={
                "short": "Stream",
                "last_year": f"{last_year} actual",
                "this_ytd": f"{this_year} YTD actual",
                "this_run_rate": f"{this_year} run-rate (annualized)",
            }
        )
        st.dataframe(
            ann_tbl.style.format(
                {
                    f"{last_year} actual": "${:,.0f}",
                    f"{this_year} YTD actual": "${:,.0f}",
                    f"{this_year} run-rate (annualized)": "${:,.0f}",
                }
            ),
            use_container_width=True,
            height=220,
            hide_index=True,
        )
        st.caption(
            "Not a 3-year total — annualized for comparison. "
            f"Run-rate = {this_year} YTD ÷ months elapsed ({as_of.month}) × 12."
        )

        with st.expander("Forecast beyond this year (collapsed)", expanded=False):
            summary_rows = []
            for origin in ("actual", "forecast"):
                sub = idf[idf["origin"] == origin] if not idf.empty else idf
                if sub is None or sub.empty:
                    continue
                for s in STREAM_ORDER:
                    amt = (
                        float(sub.loc[sub["stream"] == s, "amount"].sum())
                        if (sub["stream"] == s).any()
                        else 0.0
                    )
                    summary_rows.append(
                        {"origin": origin, "stream": STREAM_SHORT.get(s, s), "total": amt}
                    )
            if summary_rows:
                sdf_sum = pd.DataFrame(summary_rows)
                piv = sdf_sum.pivot(index="stream", columns="origin", values="total").fillna(0.0)
                for col in ("actual", "forecast"):
                    if col not in piv.columns:
                        piv[col] = 0.0
                piv = piv[["actual", "forecast"]]
                st.dataframe(
                    piv.style.format({"actual": "${:,.0f}", "forecast": "${:,.0f}"}),
                    use_container_width=True,
                    height=220,
                )
                st.caption(
                    "Forecast column is the projection window total (can span multiple years) — "
                    "use annual totals above for year-to-year decisions."
                )

        # 2028 independence check (was "Dependency scorecard")
        dep = insights_eng.dependency_scorecard(idf, actuals=actuals, daily=res["daily"])
        level = dep.get("level") or "neutral"
        pre = dep.get("side_gig") or {}
        pri = dep.get("secondary_primary") or {}

        pre_level = pre.get("level") or "neutral"
        pri_level = pri.get("level") or "neutral"
        colors = {"green": "#1b6b3a", "orange": "#9a6700", "red": "#9b1c1c", "neutral": "#5b6575"}
        bgs = {"green": "#e6f7ed", "orange": "#fff7e6", "red": "#fdeceb", "neutral": "#f3f4f6"}
        icons = {"green": "✅", "orange": "⚠️", "red": "🚨", "neutral": "•"}

        st.markdown("#### Can Alex carry the household?")
        st.caption(
            "Your goal: by **2028**, bills run on Alex's income. "
            "Jordan's paycheck and side_gig pay are OK until the dates below — "
            "after that they should go to **Savings**, not rent/food."
        )

        # Big overall pill
        overall_msg = {
            "green": "On track — not leaning on Jordan past the plan dates",
            "orange": "Watch — some months after the plan still use Jordan money for bills",
            "red": "Dependent — often using Jordan money for bills after the plan dates",
            "neutral": "Not enough income history yet",
        }.get(level, "—")
        st.markdown(
            f"""
<div style="border-radius:16px;border:1px solid {colors.get(level,'#5b6575')}55;background:{bgs.get(level,'#f3f4f6')};
padding:1rem 1.1rem;margin:0.35rem 0 0.85rem;">
  <div style="font-weight:750;color:{colors.get(level,'#5b6575')};font-size:1.15rem;">
    {icons.get(level,'•')} {overall_msg}
  </div>
</div>
""",
            unsafe_allow_html=True,
        )

        c1, c2 = st.columns(2)
        with c1:
            pl = pre_level
            st.markdown(
                f"""
<div style="border-radius:14px;border:1px solid {colors.get(pl,'#999')}44;background:{bgs.get(pl,'#f3f4f6')};
padding:0.85rem 1rem;min-height:7.5rem;">
  <div style="font-size:1.4rem;">🏫</div>
  <div style="font-weight:700;color:#111827;margin-top:0.2rem;">Side gig paycheck</div>
  <div style="color:#4b5563;font-size:0.9rem;margin:0.25rem 0;">OK to use for bills through <b>{pre.get('plan_end', SIDE_GIG_PLAN_END_MONTH)}</b></div>
  <div style="font-weight:700;color:{colors.get(pl,'#333')};margin-top:0.45rem;">
    {icons.get(pl,'•')} {"Still inside the window" if pl=="green" else ("Watch — still covering bills after" if pl=="orange" else ("Past the window — still covering bills" if pl=="red" else "—"))}
  </div>
</div>
""",
                unsafe_allow_html=True,
            )
        with c2:
            pl = pri_level
            st.markdown(
                f"""
<div style="border-radius:14px;border:1px solid {colors.get(pl,'#999')}44;background:{bgs.get(pl,'#f3f4f6')};
padding:0.85rem 1rem;min-height:7.5rem;">
  <div style="font-size:1.4rem;">💜</div>
  <div style="font-weight:700;color:#111827;margin-top:0.2rem;">Jordan's \\$1,500 paycheck</div>
  <div style="color:#4b5563;font-size:0.9rem;margin:0.25rem 0;">OK for bills through <b>{pri.get('sunset', SECONDARY_SUNSET_MONTH)}</b> · then \\$0 in the plan</div>
  <div style="font-weight:700;color:{colors.get(pl,'#333')};margin-top:0.45rem;">
    {icons.get(pl,'•')} {"Still inside the window" if pl=="green" else ("Watch — 2028+ still covering bills" if pl=="orange" else ("2028+ still covering bills" if pl=="red" else "—"))}
  </div>
</div>
""",
                unsafe_allow_html=True,
            )

        with st.expander("What this checks (optional)", expanded=False):
            st.markdown(
                """
This is **not** a monthly budget grade. It only asks:

1. After side_gig pay is supposed to stop (**~Feb 2027**), are those dollars still paying living expenses instead of going to Savings?
2. From **2028** on, is Jordan's \\$1,500 still required for bills? (Plan says Alex carries it; her pay → Savings when present.)

Green = you’re staying inside those windows. It turns yellow/red only if the *future* months show Jordan money still propping up operating cash.
"""
            )
            if dep.get("caption"):
                st.caption(_md(dep.get("caption")))

    # ----- Expense section -----
    st.markdown("## Expenses")
    st.caption(
        "Lifestyle picture first, then drill into Utilities / Groceries stacks. "
        "Bank CSV actuals only."
    )
    sdf = insights_eng.spend_frame(actuals)
    if sdf.empty:
        st.info("No bank_csv spend actuals yet — import on the Import page.")
    else:
        years = sorted({int(y) for y in sdf["year"].unique()})
        parents_ranked = insights_eng.parents_with_spend(sdf)
        parent_opts = ["All parents"] + parents_ranked
        default_parent = "All parents"
        for pref in FEATURED_EXPENSE_PARENTS:
            if pref in parents_ranked:
                default_parent = pref
                break
        if "insights_parent" not in st.session_state:
            st.session_state["insights_parent"] = default_parent
        elif st.session_state["insights_parent"] not in parent_opts:
            st.session_state["insights_parent"] = default_parent

        f1, f2, f3 = st.columns([1, 1.2, 1])
        with f1:
            year_opts = ["All"] + [str(y) for y in years]
            year_default = str(date.today().year) if str(date.today().year) in year_opts else "All"
            if "insights_year" not in st.session_state:
                st.session_state["insights_year"] = year_default
            year_sel = st.selectbox(
                "Year filter",
                options=year_opts,
                key="insights_year",
            )
        with f2:
            parent_sel = st.selectbox(
                "Parent category",
                parent_opts,
                key="insights_parent",
                help="Featured: Utilities, Groceries, Dining, Housing, Shopping — works for any parent.",
            )
        with f3:
            n_months = st.slider(
                "Months (charts)",
                min_value=4,
                max_value=min(18, max(4, len(sdf["month"].unique()))),
                value=min(12, len(sdf["month"].unique())),
                key="insights_n_months",
            )

        # Chip buttons must use on_click — assigning insights_parent after the
        # selectbox (same key) is created raises StreamlitWidgetAlreadyInstantiatedError.
        def _insights_set_parent(parent: str) -> None:
            st.session_state["insights_parent"] = parent

        chip_cols = st.columns(len(FEATURED_EXPENSE_PARENTS) + 1)
        with chip_cols[0]:
            st.button(
                "All",
                key="insights_chip_all",
                use_container_width=True,
                on_click=_insights_set_parent,
                args=("All parents",),
            )
        for i, feat in enumerate(FEATURED_EXPENSE_PARENTS):
            with chip_cols[i + 1]:
                disabled = feat not in parents_ranked
                label = feat if not disabled else f"{feat}*"
                st.button(
                    label,
                    key=f"insights_chip_{feat}",
                    disabled=disabled,
                    use_container_width=True,
                    on_click=_insights_set_parent,
                    args=(feat,),
                )

        sdf_f = sdf.copy()
        if year_sel != "All":
            sdf_f = sdf_f[sdf_f["year"] == int(year_sel)]

        all_m = sorted(sdf_f["month"].unique())
        show_months = all_m[-n_months:] if all_m else []
        sdf_w = sdf_f[sdf_f["month"].isin(show_months)] if show_months else sdf_f

        # ----- 1) Beyond lights-on discretionary chart (leads Expenses) -----
        st.markdown("### Beyond keeping the lights on — where money goes")
        disc_year = int(year_sel) if year_sel != "All" else None
        disc = insights_eng.discretionary_spend_by_parent(
            sdf_f if year_sel != "All" else sdf,
            months=show_months if year_sel == "All" else None,
            year=disc_year,
            exclude_parents=DISCRETIONARY_EXCLUDE_PARENTS,
        )
        if disc.empty:
            st.info("No discretionary spend in this window.")
        else:
            range_txt = (
                insights_eng.month_range_plain(show_months)
                if show_months
                else (str(disc_year) if disc_year else "all actuals")
            )
            st.caption(
                f"Share of lifestyle spend · {range_txt}. "
                "Excludes Housing, Utilities, Insurance, Debt, School, Transfers/Savings, "
                "and Student Loans. Credit Cards (non-loan) stay in — lifestyle signal."
            )
            try:
                import altair as alt

                top_disc = disc.head(10).copy()
                bars = (
                    alt.Chart(top_disc)
                    .mark_bar()
                    .encode(
                        y=alt.Y("parent:N", sort="-x", title=None),
                        x=alt.X("amount:Q", title="Spend ($)"),
                        color=alt.Color("label:N", legend=None),
                        tooltip=[
                            "parent",
                            alt.Tooltip("amount:Q", format="$,.0f"),
                            alt.Tooltip("pct:Q", format=".0f", title="%"),
                        ],
                    )
                )
                txt = (
                    alt.Chart(top_disc)
                    .mark_text(align="left", dx=4, fontSize=11)
                    .encode(
                        y=alt.Y("parent:N", sort="-x"),
                        x=alt.X("amount:Q"),
                        text=alt.Text("label:N"),
                    )
                )
                st.altair_chart(
                    (bars + txt).properties(height=max(260, 28 * len(top_disc))),
                    use_container_width=True,
                )
            except Exception:
                _disc_fb = disc.head(10)[["parent", "amount"]].copy()
                labeled_bars(
                    _disc_fb,
                    x_col="parent",
                    y_col="amount",
                    horizontal=True,
                    height=max(260, 28 * len(_disc_fb)),
                )

        with st.expander("Show numbers table", expanded=False):
            show_d = disc[["parent", "amount", "pct"]].rename(
                columns={"parent": "Parent", "amount": "$", "pct": "% of discretionary"}
            )
            st.dataframe(
                show_d.style.format({"$": "${:,.0f}", "% of discretionary": "{:.0f}%"}),
                use_container_width=True,
                height=min(360, 60 + 28 * min(len(show_d), 12)),
                hide_index=True,
            )

        if sdf_w.empty:
            st.warning("No spend in the selected filters.")
        else:
            range_plain = insights_eng.month_range_plain(list(show_months))
            n_win = len(show_months)

            # ----- Parent → subcategory MoM (stacked) -----
            if parent_sel != "All parents":
                st.markdown(
                    f"#### {parent_sel} — by month"
                    + (f" · {range_plain}" if range_plain else "")
                    + (f" (last {n_win} months)" if n_win else "")
                )
                st.caption(
                    f"How **{parent_sel}** breaks down each month "
                    "(e.g. FPL vs Water vs AT&T)."
                )
                sub_wide, sub_pct = insights_eng.subcategory_mom_matrix(
                    sdf_w, parent_sel, show_months
                )
                if not sub_wide.empty:
                    nonzero_cols = [c for c in sub_wide.columns if float(sub_wide[c].sum()) > 0]
                    sub_wide = sub_wide[nonzero_cols] if nonzero_cols else sub_wide
                    sub_pct = sub_pct[nonzero_cols] if nonzero_cols and not sub_pct.empty else sub_pct

                if sub_wide.empty or float(sub_wide.to_numpy().sum()) <= 0:
                    st.info(f"No subcategory spend for {parent_sel} in this window.")
                else:
                    try:
                        import altair as alt

                        long = (
                            sub_wide.reset_index()
                            .melt(id_vars="month", var_name="subcategory", value_name="spend")
                        )
                        pct_long = (
                            sub_pct.reset_index()
                            .melt(id_vars="month", var_name="subcategory", value_name="pct")
                            if not sub_pct.empty
                            else None
                        )
                        if pct_long is not None:
                            long = long.merge(pct_long, on=["month", "subcategory"], how="left")
                        else:
                            long["pct"] = None
                        long = long[long["spend"] > 0].copy()
                        # Label small segments sparsely — only when share ≥ 12% of month
                        long["label_txt"] = long.apply(
                            lambda r: (
                                f"${r['spend']:,.0f}"
                                if (r.get("pct") or 0) >= 12
                                else ""
                            ),
                            axis=1,
                        )
                        sub_order = list(sub_wide.columns)
                        ord_map = {s: i for i, s in enumerate(sub_order)}
                        long["_stack_ord"] = long["subcategory"].map(ord_map)
                        month_tot = (
                            long.groupby("month", as_index=False)["spend"]
                            .sum()
                        )
                        month_tot["total_txt"] = month_tot["spend"].map(
                            lambda v: f"${v:,.0f}"
                        )
                        stacked = (
                            alt.Chart(long)
                            .mark_bar()
                            .encode(
                                x=alt.X("month:N", title="Month", sort=list(show_months)),
                                y=alt.Y("spend:Q", title="Spend ($)", stack="zero"),
                                color=alt.Color(
                                    "subcategory:N",
                                    title="Sub",
                                    sort=sub_order,
                                    legend=alt.Legend(orient="right"),
                                ),
                                order=alt.Order("_stack_ord:Q"),
                                tooltip=[
                                    "month",
                                    "subcategory",
                                    alt.Tooltip("spend:Q", format="$,.0f", title="$"),
                                    alt.Tooltip("pct:Q", format=".1f", title="% of month"),
                                ],
                            )
                        )
                        stack_txt = (
                            alt.Chart(long)
                            .mark_text(baseline="middle", fontSize=10, color="white")
                            .encode(
                                x=alt.X("month:N", sort=list(show_months)),
                                y=alt.Y("spend:Q", stack="zero"),
                                detail="subcategory:N",
                                order=alt.Order("_stack_ord:Q"),
                                text="label_txt:N",
                            )
                        )
                        tot_txt = (
                            alt.Chart(month_tot)
                            .mark_text(
                                dy=-8,
                                fontSize=11,
                                fontWeight="bold",
                                color="#1e293b",
                            )
                            .encode(
                                x=alt.X("month:N", sort=list(show_months)),
                                y=alt.Y("spend:Q"),
                                text="total_txt:N",
                            )
                        )
                        st.altair_chart(
                            (stacked + stack_txt + tot_txt).properties(height=270),
                            use_container_width=True,
                        )
                    except Exception:
                        _sub_long = (
                            sub_wide.reset_index()
                            .melt(id_vars="month", var_name="subcategory", value_name="spend")
                        )
                        labeled_bars(
                            _sub_long,
                            x_col="month",
                            y_col="spend",
                            color_col="subcategory",
                            height=270,
                            x_sort=list(show_months),
                            color_domain=list(sub_wide.columns),
                            stack="zero",
                        )
                    st.caption(
                        f"Dollar labels on larger segments · month totals on top · "
                        f"**{parent_sel}**"
                    )

                    with st.expander("Show numbers table", expanded=False):
                        t1, t2 = st.columns(2)
                        with t1:
                            st.markdown("##### Dollars")
                            dollar_tbl = sub_wide.copy()
                            dollar_tbl.loc["TOTAL"] = dollar_tbl.sum(axis=0)
                            st.dataframe(
                                dollar_tbl.style.format("${:,.0f}"),
                                use_container_width=True,
                                height=min(420, 80 + 28 * (len(dollar_tbl) + 1)),
                            )
                        with t2:
                            st.markdown("##### % of that month's parent")
                            pct_tbl = sub_pct.copy()
                            st.dataframe(
                                pct_tbl.style.format(
                                    lambda x: "—" if pd.isna(x) else f"{x:.0f}%"
                                ),
                                use_container_width=True,
                                height=min(420, 80 + 28 * (len(pct_tbl) + 1)),
                            )

                    # This month vs last month (grouped by subcategory) — not combined totals
                    cmp_df, m_cur, m_prev, cmp_caption = (
                        insights_eng.subcategory_month_compare(
                            sdf_w, parent_sel, show_months
                        )
                    )
                    if not cmp_df.empty and float(cmp_df["spend"].sum()) > 0:
                        st.markdown(
                            f"#### {parent_sel} — this month vs last month"
                        )
                        if cmp_caption:
                            st.caption(_md(cmp_caption))

                        cmp_pos = cmp_df[cmp_df["spend"] > 0].copy()
                        # Order subs by current (or prior) spend desc
                        cur_tot = (
                            cmp_pos[cmp_pos["month_role"] == "Current"]
                            .groupby("subcategory")["spend"]
                            .sum()
                            .sort_values(ascending=False)
                        )
                        if cur_tot.empty:
                            cur_tot = (
                                cmp_pos.groupby("subcategory")["spend"]
                                .sum()
                                .sort_values(ascending=False)
                            )
                        sub_order = list(cur_tot.index)
                        role_order = ["Prior", "Current"]
                        cmp_pos["label_txt"] = cmp_pos["spend"].map(
                            lambda v: f"${v:,.0f}"
                        )
                        try:
                            import altair as alt

                            n_subs = max(1, len(sub_order))
                            bar_size = max(10, min(22, int(280 / max(n_subs, 1))))
                            grouped = (
                                alt.Chart(cmp_pos)
                                .mark_bar(size=bar_size)
                                .encode(
                                    x=alt.X(
                                        "subcategory:N",
                                        title=None,
                                        sort=sub_order,
                                        axis=alt.Axis(
                                            labelAngle=-30,
                                            labelFontSize=11,
                                            labelLimit=120,
                                        ),
                                    ),
                                    xOffset=alt.XOffset(
                                        "month_role:N", sort=role_order
                                    ),
                                    y=alt.Y("spend:Q", title="Spend ($)"),
                                    color=alt.Color(
                                        "month_role:N",
                                        title=None,
                                        sort=role_order,
                                        scale=alt.Scale(
                                            domain=role_order,
                                            range=["#94a3b8", "#0d9488"],
                                        ),
                                        legend=alt.Legend(orient="top", direction="horizontal"),
                                    ),
                                    tooltip=[
                                        "subcategory",
                                        "month_role",
                                        "month",
                                        alt.Tooltip("spend:Q", format="$,.0f", title="$"),
                                    ],
                                )
                            )
                            bar_labels = (
                                alt.Chart(cmp_pos)
                                .mark_text(dy=-7, fontSize=10, color="#334155")
                                .encode(
                                    x=alt.X("subcategory:N", sort=sub_order),
                                    xOffset=alt.XOffset(
                                        "month_role:N", sort=role_order
                                    ),
                                    y=alt.Y("spend:Q"),
                                    text="label_txt:N",
                                )
                            )
                            st.altair_chart(
                                (grouped + bar_labels).properties(height=240),
                                use_container_width=True,
                            )
                            st.caption("Each pair is this month vs last month.")
                        except Exception:
                            # Fallback: side-by-side pivot Prior/Current
                            pivot = (
                                cmp_pos.pivot_table(
                                    index="subcategory",
                                    columns="month_role",
                                    values="spend",
                                    aggfunc="sum",
                                )
                                .reindex(sub_order)
                                .fillna(0.0)
                            )
                            for col in role_order:
                                if col not in pivot.columns:
                                    pivot[col] = 0.0
                            _cmp_long = (
                                pivot[role_order]
                                .reset_index()
                                .melt(id_vars="subcategory", var_name="month_role", value_name="spend")
                            )
                            labeled_bars(
                                _cmp_long,
                                x_col="subcategory",
                                y_col="spend",
                                color_col="month_role",
                                height=240,
                                x_sort=sub_order,
                                color_domain=role_order,
                                color_range=["#94a3b8", "#0d9488"],
                            )

                        # Compact Prior | Current | Δ table (always on screen)
                        pivot = (
                            cmp_pos.pivot_table(
                                index="subcategory",
                                columns="month_role",
                                values="spend",
                                aggfunc="sum",
                            )
                            .reindex(sub_order)
                            .fillna(0.0)
                        )
                        for col in role_order:
                            if col not in pivot.columns:
                                pivot[col] = 0.0
                        pivot = pivot[role_order]
                        pivot["Δ"] = pivot["Current"] - pivot["Prior"]
                        st.dataframe(
                            pivot.style.format("${:,.0f}"),
                            use_container_width=True,
                            height=min(220, 48 + 28 * min(len(pivot) + 1, 10)),
                        )

                        # Plain-English top deltas
                        if m_prev and m_cur:
                            deltas = []
                            for sub in sub_order[:6]:
                                cur_v = float(
                                    cmp_pos.loc[
                                        (cmp_pos["subcategory"] == sub)
                                        & (cmp_pos["month_role"] == "Current"),
                                        "spend",
                                    ].sum()
                                )
                                prev_v = float(
                                    cmp_pos.loc[
                                        (cmp_pos["subcategory"] == sub)
                                        & (cmp_pos["month_role"] == "Prior"),
                                        "spend",
                                    ].sum()
                                )
                                d = cur_v - prev_v
                                if abs(d) < 0.5:
                                    continue
                                sign = "+" if d >= 0 else "−"
                                deltas.append(f"{sub} {sign}\\${abs(d):,.0f}")
                            if deltas:
                                st.markdown("**Δ:** " + " · ".join(deltas))

                wide_one = insights_eng.monthly_spend_by_parent(sdf_w, show_months)
                if parent_sel in wide_one.columns:
                    st.markdown(f"#### {parent_sel} total (MoM) · {range_plain}")
                    _tot_df = wide_one[[parent_sel]].reset_index()
                    # index name may be "month"
                    if _tot_df.columns[0] != "month":
                        _tot_df = _tot_df.rename(columns={_tot_df.columns[0]: "month"})
                    labeled_bars(
                        _tot_df,
                        x_col="month",
                        y_col=parent_sel,
                        height=200,
                        x_sort=list(_tot_df["month"]),
                    )

                avg_df = insights_eng.parent_averages_and_mom(sdf_w, show_months)
                avg_df = avg_df[avg_df["parent"] == parent_sel]
                if not avg_df.empty:
                    with st.expander("Parent averages & MoM", expanded=False):
                        show = avg_df[["parent", "avg", "latest", "delta", "delta_pct"]].copy()
                        # Plain-English month names in caption
                        lm = avg_df["latest_month"].iloc[0]
                        pm = avg_df["prior_month"].iloc[0]
                        if lm and pm:
                            st.caption(
                                f"Change: {insights_eng.month_key_short(str(lm))} vs "
                                f"{insights_eng.month_key_short(str(pm))}"
                            )
                        show = show.rename(
                            columns={
                                "avg": "Avg $/mo",
                                "latest": "Latest $",
                                "delta": "Δ $",
                                "delta_pct": "Δ %",
                            }
                        )
                        st.dataframe(
                            show.style.format(
                                {
                                    "Avg $/mo": "${:,.0f}",
                                    "Latest $": "${:,.0f}",
                                    "Δ $": lambda x: "—" if pd.isna(x) else f"${x:,.0f}",
                                }
                            ),
                            use_container_width=True,
                            height=100,
                            hide_index=True,
                        )

            else:
                # All parents — overview
                wide = insights_eng.monthly_spend_by_parent(sdf_w, show_months)
                e1, e2 = st.columns([1.4, 1])
                with e1:
                    st.markdown(f"#### MoM spend by parent · {range_plain}")
                    totals = wide.sum(axis=0).sort_values(ascending=False)
                    top = list(totals.head(8).index)
                    _mom_long = wide[top].reset_index()
                    if _mom_long.columns[0] != "month":
                        _mom_long = _mom_long.rename(columns={_mom_long.columns[0]: "month"})
                    _mom_long = _mom_long.melt(
                        id_vars="month", var_name="parent", value_name="amount"
                    )
                    labeled_bars(
                        _mom_long,
                        x_col="month",
                        y_col="amount",
                        color_col="parent",
                        height=300,
                        x_sort=list(wide.index),
                        color_domain=top,
                        stack="zero",
                    )
                with e2:
                    st.markdown("#### Latest complete month mix")
                    latest_m = insights_eng.latest_complete_month(sdf_w)
                    if latest_m and latest_m in wide.index:
                        pie_s = wide.loc[latest_m]
                        pie_s = pie_s[pie_s > 0].sort_values(ascending=False)
                        st.caption(f"**{insights_eng.month_key_label(latest_m)}**")
                        try:
                            import altair as alt

                            pie_df = pie_s.reset_index()
                            pie_df.columns = ["parent", "spend"]
                            tot = float(pie_df["spend"].sum())
                            pie_df["pct"] = 100.0 * pie_df["spend"] / tot if tot else 0.0
                            pie_df["label"] = [
                                insights_eng.chart_label_amt_pct(r["parent"], r["spend"], r["pct"])
                                for _, r in pie_df.iterrows()
                            ]
                            chart = (
                                alt.Chart(pie_df)
                                .mark_arc(innerRadius=40)
                                .encode(
                                    theta="spend:Q",
                                    color=alt.Color(
                                        "label:N",
                                        title="Parent",
                                        legend=alt.Legend(labelLimit=260),
                                    ),
                                    tooltip=[
                                        "parent",
                                        alt.Tooltip("spend:Q", format="$,.0f"),
                                        alt.Tooltip("pct:Q", format=".0f", title="%"),
                                    ],
                                )
                                .properties(height=280)
                            )
                            st.altair_chart(chart, use_container_width=True)
                        except Exception:
                            _pie_fb = pie_s.reset_index()
                            _pie_fb.columns = ["parent", "spend"]
                            labeled_bars(
                                _pie_fb,
                                x_col="parent",
                                y_col="spend",
                                horizontal=True,
                                height=280,
                            )
                    else:
                        st.write("No complete month in window.")

                with st.expander("Trends & averages", expanded=False):
                    totals = wide.sum(axis=0).sort_values(ascending=False)
                    top = list(totals.head(6).index)
                    st.line_chart(wide[top], height=260)
                    avg_df = insights_eng.parent_averages_and_mom(sdf_w, show_months)
                    if not avg_df.empty:
                        show = avg_df[["parent", "avg", "latest", "delta", "delta_pct"]].copy()
                        show = show.rename(
                            columns={
                                "avg": "Avg $/mo",
                                "latest": "Latest $",
                                "delta": "Δ $",
                                "delta_pct": "Δ %",
                            }
                        )
                        st.dataframe(
                            show.style.format(
                                {
                                    "Avg $/mo": "${:,.0f}",
                                    "Latest $": "${:,.0f}",
                                    "Δ $": lambda x: "—" if pd.isna(x) else f"${x:,.0f}",
                                }
                            ),
                            use_container_width=True,
                            height=min(360, 60 + 28 * min(len(show), 12)),
                            hide_index=True,
                        )

                st.info(
                    "Pick a **parent** (or Utilities / Groceries chip) for "
                    "month-over-month subcategory mix with \\$ labels."
                )

            with st.expander("Seasonality callouts", expanded=False):
                season_df = sdf_f[sdf_f["month"].isin(show_months)] if show_months else sdf_f
                for line in insights_eng.seasonality_callouts(season_df):
                    st.markdown(_md(f"- {line}"))



    # ----- Budget vs Actual -----
    st.markdown("## Budget vs Actual")
    st.caption(
        "Plan (rules) vs what Chase actually spent. "
        f"Flags when a category is off by \\${DEFAULT_MOM_VARIANCE_THRESHOLD:,.0f} "
        f"this month or \\${DEFAULT_QOQ_VARIANCE_THRESHOLD:,.0f} over 3 months."
    )

    def _flux_status_card_html(*, emoji: str, title: str, body: str, tone: str = "neutral") -> str:
        styles = {
            "good": ("#e6f7ed", "#1b6b3a", "#8ecfa6"),
            "warn": ("#fff7e6", "#9a6700", "#e2c48a"),
            "neutral": ("#eef4ff", "#1e3a8a", "#b6c8ee"),
        }
        bg, fg, border = styles.get(tone, styles["neutral"])
        return (
            f'<div style="border-radius:14px;border:1px solid {border};background:{bg};'
            f'padding:0.85rem 1rem;min-height:6.4rem;">'
            f'<div style="font-size:1.45rem;line-height:1;">{emoji}</div>'
            f'<div style="font-weight:750;color:{fg};margin-top:0.3rem;font-size:1.02rem;">'
            f"{title}</div>"
            f'<div style="color:#374151;margin-top:0.25rem;font-size:0.9rem;line-height:1.35;">'
            f"{body}</div>"
            f"</div>"
        )

    # Month options from actuals (prefer complete months)
    _bv_months = sorted(sdf["month"].unique()) if not sdf.empty else []
    if not _bv_months:
        st.info("Import bank_csv actuals to compare budget vs spend.")
    else:
        _default_bv = insights_eng.latest_complete_month(sdf) or _bv_months[-1]
        bv1, bv2 = st.columns([1, 1])
        with bv1:
            bv_month = st.selectbox(
                "Month",
                options=_bv_months,
                index=_bv_months.index(_default_bv) if _default_bv in _bv_months else len(_bv_months) - 1,
                key="insights_bv_month",
            )
        with bv2:
            bv_parent_opts = ["All parents"] + insights_eng.parents_with_spend(sdf)
            bv_parent = st.selectbox(
                "Parent (optional drill)",
                bv_parent_opts,
                key="insights_bv_parent",
                help="All parents for the bar chart; pick one to drill subcategory variance.",
            )
        with st.expander("Adjust sensitivity", expanded=False):
            sv1, sv2 = st.columns(2)
            with sv1:
                mom_thr = st.slider(
                    "Flag if this month is off plan by more than \\$___",
                    min_value=int(MOM_THRESHOLD_RANGE[0]),
                    max_value=int(MOM_THRESHOLD_RANGE[1]),
                    value=int(DEFAULT_MOM_VARIANCE_THRESHOLD),
                    step=50,
                    format="$%d",
                    key="insights_bv_mom_thr",
                )
            with sv2:
                qoq_thr = st.slider(
                    "Flag if last 3 months combined are off plan by more than $___",
                    min_value=int(QOQ_THRESHOLD_RANGE[0]),
                    max_value=int(QOQ_THRESHOLD_RANGE[1]),
                    value=int(DEFAULT_QOQ_VARIANCE_THRESHOLD),
                    step=100,
                    format="$%d",
                    key="insights_bv_qoq_thr",
                )

        trailing = insights_eng.trailing_month_keys(bv_month, 3)
        need_months = sorted(set(trailing) | {bv_month})
        twin_start = settings.get("start_date")
        bdf = insights_eng.budget_spend_frame(
            rules,
            planned,
            need_months,
            approximate_pre_start=True,
            twin_start=twin_start,
        )
        score = insights_eng.variance_scorecard(
            sdf,
            bdf,
            bv_month,
            mom_threshold=float(mom_thr),
            qoq_threshold=float(qoq_thr),
            trailing_n=3,
            as_of=date.today(),
        )
        parent_tbl = score["parent_table"]
        mom_flags = score.get("mom_flags") or []
        qoq_flags = score.get("qoq_flags") or []
        month_long = insights_eng.month_label_long(bv_month)
        n_mom = len(mom_flags)
        n_qoq = len(qoq_flags)
        mom_word = "category" if n_mom == 1 else "categories"
        qoq_word = "category" if n_qoq == 1 else "categories"
        mom_body = (
            "On track"
            if n_mom == 0
            else f"{n_mom} {mom_word} off by ≥\\${mom_thr:,.0f}"
        )
        qoq_body = (
            "On track"
            if n_qoq == 0
            else f"{n_qoq} {qoq_word} off by ≥\\${qoq_thr:,.0f} combined"
        )

        sc1, sc2, sc3 = st.columns(3)
        with sc1:
            st.markdown(
                _flux_status_card_html(
                    emoji="📅",
                    title=month_long,
                    body="Selected month vs plan",
                    tone="neutral",
                ),
                unsafe_allow_html=True,
            )
        with sc2:
            st.markdown(
                _flux_status_card_html(
                    emoji="✅" if n_mom == 0 else "⚠️",
                    title="This month",
                    body=mom_body,
                    tone="good" if n_mom == 0 else "warn",
                ),
                unsafe_allow_html=True,
            )
        with sc3:
            st.markdown(
                _flux_status_card_html(
                    emoji="✅" if n_qoq == 0 else "⚠️",
                    title="Last 3 months",
                    body=qoq_body,
                    tone="good" if n_qoq == 0 else "warn",
                ),
                unsafe_allow_html=True,
            )
        st.caption(_md(score.get("caption") or ""))
        partial_note = score.get("partial_month_note") or ""
        if partial_note:
            st.info(_md(partial_note))
        extra_meta = score.get("mortgage_extra_savings") or {}
        extra_note = score.get("mortgage_extra_note") or ""
        if float(score.get("mortgage_extra_applied") or 0) > 0.005:
            sav_msg = insights_eng.savings_flux_status_message(extra_meta)
            if sav_msg and insights_eng.mortgage_extra_on_target(extra_meta):
                st.success(_md(f"**On target — Savings.** {sav_msg}"))
            elif sav_msg:
                st.warning(_md(sav_msg))
            elif extra_note:
                st.info(_md(extra_note))
        elif extra_note:
            st.info(_md(extra_note))
        excl_notes = score.get("exclusion_notes") or []
        if excl_notes:
            st.caption(_md(" · ".join(excl_notes)))


        adhoc_flags = score.get("unbudgeted_adhoc_flags") or []
        if adhoc_flags:
            st.markdown("#### Unbudgeted / ad hoc (no plan line)")
            st.caption(
                "These hit Chase but are not on the recurring forecast "
                "(e.g. tutoring). Not added as automatic bills — review when they spike."
            )
            for f in adhoc_flags[:6]:
                st.markdown(
                    _md(
                        f"- **{f.get('subcategory') or f.get('parent')}**: "
                        f"spent ${f['actual']:,.0f} · plan ${f['budgeted']:,.0f} "
                        f"(ad hoc)"
                    )
                )

        # Skip Transfers/Savings over-plan cards — over-saving / mortgage credit is OK
        _flux_src = []
        for f in (mom_flags + qoq_flags):
            if f.get("parent") == "Transfers / Savings":
                d = float(f.get("delta") or f.get("cum_delta") or 0.0)
                if d >= 0:
                    continue  # ahead of plan — not a miss
            _flux_src.append(f)
        flux_cards = [insights_eng.format_flux_card(f) for f in _flux_src]
        flux_cards.sort(key=lambda c: c["abs_delta"], reverse=True)
        if flux_cards:
            shown_cards = flux_cards[:6]
            rest_cards = flux_cards[6:]
            for row_i in range(0, len(shown_cards), 3):
                row = shown_cards[row_i : row_i + 3]
                cols = st.columns(3)
                for col, card in zip(cols, row):
                    with col:
                        st.markdown(_md(card["html"]), unsafe_allow_html=True)
            if rest_cards:
                with st.expander(f"+{len(rest_cards)} more", expanded=False):
                    for row_i in range(0, len(rest_cards), 3):
                        row = rest_cards[row_i : row_i + 3]
                        cols = st.columns(3)
                        for col, card in zip(cols, row):
                            with col:
                                st.markdown(_md(card["html"]), unsafe_allow_html=True)

        # Pictorial: budget vs actual bars by parent
        chart_src = parent_tbl.copy() if parent_tbl is not None else pd.DataFrame()
        if bv_parent != "All parents" and not chart_src.empty:
            chart_src = chart_src[chart_src["parent"] == bv_parent]
        if chart_src.empty:
            st.warning(f"No budget or actual spend rows for {month_long}.")
        else:
            st.markdown(f"#### Where {month_long} landed vs plan")
            flagged_parents = {f["parent"] for f in mom_flags}
            try:
                import altair as alt

                long_bv = chart_src.melt(
                    id_vars=["parent"],
                    value_vars=["budgeted", "actual"],
                    var_name="series",
                    value_name="amount",
                )
                long_bv["series"] = long_bv["series"].map(
                    {"budgeted": "Budget", "actual": "Actual"}
                )
                # Limit to top parents by max(budget,actual) for readability
                if bv_parent == "All parents":
                    tops = (
                        chart_src.assign(
                            _m=chart_src[["budgeted", "actual"]].max(axis=1)
                        )
                        .sort_values("_m", ascending=False)
                        .head(10)["parent"]
                        .tolist()
                    )
                    long_bv = long_bv[long_bv["parent"].isin(tops)]
                long_bv = long_bv.copy()
                long_bv["color_key"] = [
                    (
                        "Budget"
                        if s == "Budget"
                        else ("Off plan" if p in flagged_parents else "Actual")
                    )
                    for s, p in zip(long_bv["series"], long_bv["parent"])
                ]
                parent_order = (
                    long_bv.groupby("parent")["amount"].max().sort_values(ascending=False).index.tolist()
                )
                if flagged_parents:
                    names = ",".join(
                        "'" + str(p).replace("'", "\\'") + "'" for p in flagged_parents
                    )
                    label_color = {
                        "expr": (
                            f"indexof([{names}], datum.value) >= 0 "
                            "? '#9a6700' : '#374151'"
                        )
                    }
                else:
                    label_color = "#374151"
                bar = (
                    alt.Chart(long_bv)
                    .mark_bar()
                    .encode(
                        x=alt.X(
                            "parent:N",
                            sort=parent_order,
                            title=None,
                            axis=alt.Axis(labelColor=label_color, labelAngle=-35),
                        ),
                        y=alt.Y("amount:Q", title="$"),
                        color=alt.Color(
                            "color_key:N",
                            scale=alt.Scale(
                                domain=["Budget", "Actual", "Off plan"],
                                range=["#94a3b8", "#5b8def", "#d97706"],
                            ),
                            legend=alt.Legend(title=None),
                        ),
                        xOffset="series:N",
                        tooltip=[
                            "parent",
                            "series",
                            alt.Tooltip("amount:Q", format="$,.0f"),
                        ],
                    )
                    .properties(height=320)
                )
                labels_df = long_bv[long_bv["amount"].abs() >= 0.5].copy()
                labels_df["_lbl"] = labels_df["amount"].map(lambda v: f"${v:,.0f}")
                if not labels_df.empty:
                    labels = (
                        alt.Chart(labels_df)
                        .mark_text(dy=-8, fontSize=10, color="#1f2937", baseline="bottom")
                        .encode(
                            x=alt.X("parent:N", sort=parent_order),
                            xOffset="series:N",
                            y=alt.Y("amount:Q"),
                            text="_lbl:N",
                        )
                    )
                    st.altair_chart(bar + labels, use_container_width=True)
                else:
                    st.altair_chart(bar, use_container_width=True)
            except Exception:
                plot_df = chart_src.set_index("parent")[["budgeted", "actual"]].head(10)
                plot_df = plot_df.rename(columns={"budgeted": "Budget", "actual": "Actual"})
                _bv_fb = (
                    plot_df.reset_index()
                    .melt(id_vars="parent", var_name="series", value_name="amount")
                )
                labeled_bars(
                    _bv_fb,
                    x_col="parent",
                    y_col="amount",
                    color_col="series",
                    height=320,
                    x_sort=list(plot_df.index),
                    color_domain=["Budget", "Actual"],
                    color_range=["#94a3b8", "#5b8def"],
                )

            # Table + subcategory drill
            show_p = parent_tbl.copy()
            if bv_parent != "All parents":
                show_p = show_p[show_p["parent"] == bv_parent]
            if not show_p.empty:
                disp = show_p[
                    ["parent", "budgeted", "actual", "delta", "abs_delta", "flagged"]
                ].copy()
                # Plain status: Savings ahead via mortgage credit is "On target", not a miss
                def _row_status(r):
                    if r["parent"] == "Transfers / Savings" and insights_eng.mortgage_extra_on_target(
                        extra_meta
                    ):
                        return "On target"
                    if r["parent"] == "Housing" and float(
                        score.get("mortgage_extra_applied") or 0
                    ) > 0.005 and abs(float(r["delta"])) < 0.5:
                        return "On target"
                    return "Flagged" if bool(r["flagged"]) else "OK"

                disp["status"] = disp.apply(_row_status, axis=1)
                disp = disp.rename(
                    columns={
                        "parent": "Parent",
                        "budgeted": "Plan $",
                        "actual": "Spent $",
                        "delta": "Off by $",
                        "abs_delta": "Abs off $",
                        "flagged": "This month flag",
                        "status": "Status",
                    }
                )
                with st.expander("Show numbers table", expanded=False):
                    if insights_eng.mortgage_extra_on_target(extra_meta):
                        st.caption(
                            "Transfers/Savings “Off by” above plan means extra SAV "
                            "transfers after the mortgage debt-payoff quota — ahead, not a miss."
                        )
                    st.dataframe(
                        disp.style.format(
                            {
                                "Plan $": "${:,.0f}",
                                "Spent $": "${:,.0f}",
                                "Off by $": "${:,.0f}",
                                "Abs off $": "${:,.0f}",
                            }
                        ),
                        use_container_width=True,
                        height=min(420, 80 + 28 * min(len(disp), 14)),
                        hide_index=True,
                    )

            drill_parent = bv_parent if bv_parent != "All parents" else None
            if drill_parent is None and mom_flags:
                # Default drill to largest this-month flag
                drill_parent = max(mom_flags, key=lambda x: x["abs_delta"])["parent"]
            # Prefer showing Savings/Housing explainers when mortgage credit applied
            if (
                drill_parent is None
                and float(score.get("mortgage_extra_applied") or 0) > 0.005
                and bv_parent == "All parents"
            ):
                drill_parent = "Transfers / Savings"
            if drill_parent:
                sub_tbl = insights_eng.budget_vs_actual_table(
                    sdf,
                    bdf,
                    bv_month,
                    parent=drill_parent,
                    level="subcategory",
                    mom_threshold=float(mom_thr),
                    as_of=date.today(),
                )
                drove_bullets = insights_eng.mortgage_extra_drove_bullets(
                    drill_parent, extra_meta
                )
                if sub_tbl.empty and not drove_bullets:
                    with st.expander(f"What drove {drill_parent}?", expanded=(bv_parent != "All parents")):
                        st.write("No subcategory rows.")
                else:
                    if not sub_tbl.empty:
                        top_subs = (
                            sub_tbl.assign(_m=sub_tbl[["budgeted", "actual"]].max(axis=1))
                            .sort_values("_m", ascending=False)
                            .head(8)
                        )
                        long_sub = top_subs.melt(
                            id_vars=["subcategory"],
                            value_vars=["budgeted", "actual"],
                            var_name="series",
                            value_name="amount",
                        )
                        long_sub["series"] = long_sub["series"].map(
                            {"budgeted": "Budget", "actual": "Actual"}
                        )
                        sub_order = top_subs["subcategory"].tolist()
                        labeled_bars(
                            long_sub,
                            x_col="subcategory",
                            y_col="amount",
                            color_col="series",
                            horizontal=True,
                            height=max(140, 32 * len(sub_order)),
                            title=f"What drove {drill_parent}?",
                            x_sort=sub_order,
                            color_domain=["Budget", "Actual"],
                            color_range=["#94a3b8", "#5b8def"],
                        )
                    expand_default = bv_parent != "All parents" or bool(drove_bullets)
                    with st.expander(
                        f"What drove {drill_parent}?",
                        expanded=expand_default,
                    ):
                        if drove_bullets:
                            for b in drove_bullets:
                                st.markdown(f"- {b}")
                            # Also offer Housing explainer when viewing Savings (and vice versa)
                            other = (
                                "Housing"
                                if drill_parent == "Transfers / Savings"
                                else (
                                    "Transfers / Savings"
                                    if drill_parent == "Housing"
                                    else None
                                )
                            )
                            if other:
                                other_bullets = insights_eng.mortgage_extra_drove_bullets(
                                    other, extra_meta
                                )
                                if other_bullets:
                                    st.markdown(f"**What drove {other}?**")
                                    for b in other_bullets:
                                        st.markdown(f"- {b}")
                        if not sub_tbl.empty:
                            sdisp = sub_tbl[
                                [
                                    "subcategory",
                                    "budgeted",
                                    "actual",
                                    "delta",
                                    "abs_delta",
                                    "flagged",
                                ]
                            ].rename(
                                columns={
                                    "subcategory": "Subcategory",
                                    "budgeted": "Plan $",
                                    "actual": "Spent $",
                                    "delta": "Off by $",
                                    "abs_delta": "Abs off $",
                                    "flagged": "Off plan",
                                }
                            )
                            if drove_bullets:
                                st.caption("Subcategory detail")
                            st.dataframe(
                                sdisp.style.format(
                                    {
                                        "Plan $": "${:,.0f}",
                                        "Spent $": "${:,.0f}",
                                        "Off by $": "${:,.0f}",
                                        "Abs off $": "${:,.0f}",
                                    }
                                ),
                                use_container_width=True,
                                height=min(360, 70 + 28 * min(len(sdisp), 12)),
                                hide_index=True,
                            )

        with st.expander("Budget proxy limitations", expanded=False):
            st.markdown(_md(BUDGET_LIMITATIONS_NOTE))
            if twin_start:
                st.caption(
                    f"Twin start_date = **{twin_start}**. "
                    "Pre-start months use approximate Data Input stamps."
                )


# ---------- REWARDS CARD / WIFE'S ALLOWANCE FAMILY CARD ----------
elif page == "Rewards Card — demo rewards card":
    st.title("Family card — Rewards Card")
    st.caption(
        "This is the card Jordan uses for everyday family spending "
        "(groceries, gas, kids, Amazon). "
        "It is **not** the checking account — paying the card still shows there."
    )

    card_rows = _black_card_rows(all_actuals)
    snap = load_black_card_snapshot()
    pending = list(snap.get("pending") or [])
    pending_purchases = [p for p in pending if (p.get("type") or "") != "Payment"]
    pending_payments = [p for p in pending if (p.get("type") or "") == "Payment"]
    pending_purchase_total = abs(sum(float(p.get("amount") or 0) for p in pending_purchases))
    pending_payment_total = sum(float(p.get("amount") or 0) for p in pending_payments)
    # Two paths to ending owed (should tie arithmetically):
    #   A) credit limit − available credit
    #   B) posted balance + pending charges
    def _fnum(v):
        try:
            return float(v) if v is not None and v != "" else None
        except (TypeError, ValueError):
            return None

    _limit_f = _fnum(snap.get("credit_limit"))
    _avail_f = _fnum(snap.get("available_credit"))
    _posted_f = _fnum(snap.get("posted_balance"))
    _pend_hdr = _fnum(snap.get("pending_header_total"))
    _pend_net = abs(_pend_hdr) if _pend_hdr is not None else float(pending_purchase_total or 0)
    _path_a = round(_limit_f - _avail_f, 2) if _limit_f is not None and _avail_f is not None else None
    _path_b = (
        round(_posted_f + _pend_net, 2) if _posted_f is not None else None
    )
    _snap_current = _fnum(snap.get("current_balance"))
    # Prefer a tied value; else Path A; else Path B; else snapshot current
    _tie = (
        _path_a is not None
        and _path_b is not None
        and abs(_path_a - _path_b) <= 0.05
    )
    if _tie:
        live_bal = _path_a
    elif _path_a is not None and _path_b is not None:
        # Mismatch: prefer explicit Chase current if present, else Path B (posted+pending)
        live_bal = _snap_current if _snap_current is not None else _path_b
    elif _path_a is not None:
        live_bal = _path_a
    elif _path_b is not None:
        live_bal = _path_b
    else:
        live_bal = _snap_current
    as_of = snap.get("as_of") or ""

    if not card_rows:
        st.info("No family-card charges imported yet. Scroll to the bottom to add the CSV.")
        _render_black_card_import_box(conn, key_prefix="black_empty")
        st.stop()

    cdf = pd.DataFrame(card_rows)
    cdf["date"] = pd.to_datetime(cdf["date"])
    cdf["year"] = cdf["date"].dt.year
    cdf["month"] = cdf["date"].dt.to_period("M").astype(str)
    cdf["txn_type"] = cdf.get("txn_type", pd.Series([""] * len(cdf))).fillna("")
    cdf["parent"] = cdf.get("parent", pd.Series(["Uncategorized"] * len(cdf))).fillna("Uncategorized")
    cdf["subcategory"] = cdf.get("subcategory", pd.Series(["Uncategorized"] * len(cdf))).fillna("Uncategorized")
    cdf["label"] = cdf.get("label", pd.Series([""] * len(cdf))).fillna("")
    cdf["amount"] = pd.to_numeric(cdf["amount"], errors="coerce").fillna(0.0)
    cdf["is_purchase"] = [
        is_card_purchase(t, a) for t, a in zip(cdf["txn_type"], cdf["amount"])
    ]
    purch = cdf[cdf["is_purchase"]].copy()
    purch["spend"] = (-purch["amount"]).clip(lower=0)
    purch["friendly"] = purch["parent"].map(_friendly_parent)
    purch["merchant"] = purch["label"].map(merchant_stem)

    today = date.today()
    this_month = f"{today.year}-{today.month:02d}"
    this_target = allowance_budget_for_month(today.year, today.month)
    this_purch = float(purch.loc[purch["month"] == this_month, "spend"].sum())
    budget_ctx = load_black_card_budget_context()
    prior_residual = float(budget_ctx.get("prior_month_residual") or 0.0)
    prior_residual_label = str(budget_ctx.get("prior_month_label") or "Still from August")
    # Mid-month Jordan story: owed from snapshot, not lagged CSV "so far"
    owed_now = float(live_bal) if live_bal is not None else 0.0
    true_sep_toward = max(0.0, round(owed_now - prior_residual, 2))
    true_over_under = round(true_sep_toward - this_target, 2)  # >0 over, <0 under
    # CSV posted so far (this_purch) kept as secondary caption only — does not drive under/over

    mom = (
        purch.groupby("month", as_index=False)["spend"]
        .sum()
        .sort_values("month")
    )
    # Average across months with real activity (skip tiny stub months)
    avg_months = mom[mom["spend"] >= 100.0]
    avg_spend = float(avg_months["spend"].mean()) if not avg_months.empty else 0.0

    year_purch = purch[purch["year"] == today.year]
    top_parents_year = (
        year_purch.groupby("friendly", as_index=False)["spend"]
        .sum()
        .sort_values("spend", ascending=False)
        .head(5)
    )
    top_merch_year = (
        year_purch.groupby("merchant", as_index=False)["spend"]
        .sum()
        .sort_values("spend", ascending=False)
        .head(5)
    )
    this_slice = purch[purch["month"] == this_month]
    top_parents_mo = (
        this_slice.groupby("friendly", as_index=False)["spend"]
        .sum()
        .sort_values("spend", ascending=False)
        .head(5)
    )
    top_merch_mo = (
        this_slice.groupby("merchant", as_index=False)["spend"]
        .sum()
        .sort_values("spend", ascending=False)
        .head(5)
    )
    buckets = [
        str(r["friendly"])
        for _, r in (top_parents_year if not top_parents_year.empty else top_parents_mo).iterrows()
    ][:3]
    bucket_txt = ", ".join(buckets) if buckets else "everyday purchases"
    ou_word = "over" if (avg_spend - 2500) > 0 else "under"
    story = (
        f"We averaged {money(avg_spend)} a month on the family card "
        f"vs the {money(2500)} we try to pay — about {money(abs(avg_spend - 2500))} {ou_word}. "
        f"Biggest buckets: {bucket_txt}. "
        f"In March 2027 the budget steps up to {money(3500)}."
    )
    st.markdown(
        f"""
<div style="border-radius:16px;border:1px solid #c5d4c8;background:linear-gradient(160deg,#eef8f1 0%,#f7fbf8 100%);
padding:1rem 1.15rem;margin:0.2rem 0 0.9rem;">
  <div style="font-size:1.12rem;font-weight:750;color:#1f2937;line-height:1.45;">{story}</div>
</div>
""",
        unsafe_allow_html=True,
    )

    # Mid-month hero cards: owed / target / true Sep / under-over (residual only if > 0)
    true_ou_kind = "expense" if true_over_under > 0 else "income"
    true_ou_signed = "neg" if true_over_under > 0 else "pos"
    true_ou_label = "Over target" if true_over_under > 0 else "Under target"
    true_ou_abs = abs(true_over_under)
    month_name_txt = f"{month_name[today.month]} so far"
    chips = [
        _pict_card_html(
            emoji="💳",
            label="Card balance (owed)",
            value_html=_fmt_pict_money(owed_now, signed=None),
            sub=f"as of {as_of}" if as_of else "Family card ••••1234",
            kind="brokerage",
        ),
        _pict_card_html(
            emoji="🎯",
            label="Monthly target",
            value_html=_fmt_pict_money(this_target, signed=None),
            sub="$2,500 now · $3,500 from Mar 2027",
            kind="savings",
        ),
    ]
    if prior_residual > 0:
        chips.append(
            _pict_card_html(
                emoji="📅",
                label=prior_residual_label,
                value_html=_fmt_pict_money(prior_residual, signed="neg"),
                sub="Leftover — not this month's spend",
                kind="expense",
            )
        )
    chips.extend(
        [
            _pict_card_html(
                emoji="🛍️",
                label="True Sep toward target",
                value_html=_fmt_pict_money(true_sep_toward, signed="neg"),
                sub=(
                    "Owed minus August leftover"
                    if prior_residual > 0
                    else "Card balance toward allowance"
                ),
                kind="expense",
            ),
            _pict_card_html(
                emoji="⚖️",
                label=true_ou_label,
                value_html=_fmt_pict_money(true_ou_abs, signed=true_ou_signed),
                sub="Based on true Sep toward target",
                kind=true_ou_kind,
            ),
            _pict_card_html(
                emoji="📊",
                label="Typical month",
                value_html=_fmt_pict_money(avg_spend, signed="neg"),
                sub="Average across this CSV year",
                kind="expense",
            ),
        ]
    )
    st.markdown(_pict_card_css(), unsafe_allow_html=True)
    st.markdown('<div class="pict-row">' + "".join(chips) + "</div>", unsafe_allow_html=True)
    if prior_residual > 0:
        st.caption(
            _md(
                f"~{money(prior_residual)} of what's owed is leftover August — not September spend. "
                f"True under target is {money(true_ou_abs)}."
                if true_over_under <= 0
                else f"~{money(prior_residual)} of what's owed is leftover August — not September spend. "
                f"True over target is {money(true_ou_abs)}."
            )
        )
    st.caption(
        _md(
            f"CSV posted {month_name_txt}: {money(this_purch)} "
            f"(secondary — lags mid-month activity; not used for under/over)."
        )
    )
    if pending_purchases or pending_payments:
        st.caption(
            _md(
                f"{len(pending_purchases)} charges still pending ({money(pending_purchase_total)}) "
                f"+ {money(pending_payment_total)} payment already sent from checking."
            )
        )

    # Arithmetic tie-out: Path A vs Path B
    if live_bal is not None and (_path_a is not None or _path_b is not None):
        st.markdown("### Final card balance")
        _tie_ok = (
            _path_a is not None
            and _path_b is not None
            and abs(_path_a - _path_b) <= 0.05
        )
        if _tie_ok:
            _badge = '<span style="color:#1b6b3a;font-weight:700;">Tie-out OK</span>'
        elif _path_a is not None and _path_b is not None:
            _badge = (
                '<span style="color:#7a4a1e;font-weight:700;">Paths differ</span>'
                f' — showing {money(live_bal)} as ending owed'
            )
        else:
            _badge = '<span style="color:#5b6475;font-weight:600;">One path only</span>'
        _a_line = (
            f"<div><strong>Path A (calculator)</strong> — credit limit {money(_limit_f)} "
            f"minus available {money(_avail_f)} = <strong>{money(_path_a)}</strong></div>"
            if _path_a is not None
            else "<div><strong>Path A (calculator)</strong> — need limit + available credit</div>"
        )
        _b_line = (
            f"<div><strong>Path B (posted + pending)</strong> — posted {money(_posted_f)} "
            f"plus pending {money(_pend_net)} = <strong>{money(_path_b)}</strong></div>"
            if _path_b is not None
            else "<div><strong>Path B (posted + pending)</strong> — need posted balance + pending</div>"
        )
        st.markdown(
            f"""
<div style="border-radius:14px;padding:0.95rem 1.1rem;margin:0.15rem 0 0.75rem;
background:linear-gradient(135deg,#eef2fb 0%,#f7f9fc 100%);border:1px solid #c5d0e8;">
  <div style="font-size:0.78rem;font-weight:700;color:#5b6475;letter-spacing:0.04em;">ENDING BALANCE OWED</div>
  <div style="font-size:1.9rem;font-weight:800;color:#1e293b;margin-top:0.1rem;">{money(live_bal)}</div>
  <div style="margin-top:0.35rem;font-size:0.9rem;">{_badge}</div>
  <div style="color:#3a4254;margin-top:0.55rem;line-height:1.55;font-size:0.95rem;">
    {_a_line}
    {_b_line}
    <div style="margin-top:0.35rem;font-size:0.88rem;color:#5b6475;">
      Both paths should match. That arithmetic check confirms the ending balance.
    </div>
  </div>
</div>
            """,
            unsafe_allow_html=True,
        )
        if pending_payments:
            st.caption(
                _md(
                    f"Payment {money(pending_payment_total)} from checking is listed under pending "
                    f"for visibility — Path B uses purchase pending only (not the payment twice)."
                )
            )

    # Live Suggested cards — recomputes from DB actuals on every run / CSV re-import
    _render_suggested_cards(card_rows)

    st.markdown("### Each month on the family card")
    st.caption(_md("Bars are purchases only (not payments). Lines mark $2,500 now and $3,500 later."))
    if mom.empty:
        st.info("No purchases to chart yet.")
    else:
        import altair as alt

        plot = mom.copy()
        plot["flag"] = [
            "Over $2,500" if float(v) > 2500 else "At or under $2,500" for v in plot["spend"]
        ]
        plot["_lbl"] = plot["spend"].map(lambda v: f"${float(v):,.0f}" if float(v) >= 0.5 else "")
        months = list(plot["month"])
        bars = (
            alt.Chart(plot)
            .mark_bar(cornerRadiusTopLeft=4, cornerRadiusTopRight=4)
            .encode(
                x=alt.X("month:N", title=None, sort=months),
                y=alt.Y("spend:Q", title=None),
                color=alt.Color(
                    "flag:N",
                    scale=alt.Scale(
                        domain=["Over $2,500", "At or under $2,500"],
                        range=["#c08457", "#6ea07a"],
                    ),
                    legend=alt.Legend(title=None, orient="bottom"),
                ),
                tooltip=[
                    alt.Tooltip("month:N", title="Month"),
                    alt.Tooltip("spend:Q", format="$,.0f", title="Spent"),
                ],
            )
        )
        txt = (
            alt.Chart(plot)
            .mark_text(dy=-8, fontSize=12, fontWeight="bold", color="#1e293b")
            .encode(x=alt.X("month:N", sort=months), y=alt.Y("spend:Q"), text="_lbl:N")
        )
        r25 = (
            alt.Chart(pd.DataFrame({"y": [2500]}))
            .mark_rule(strokeDash=[6, 4], color="#2f6f4e", strokeWidth=2)
            .encode(y="y:Q")
        )
        r35 = (
            alt.Chart(pd.DataFrame({"y": [3500]}))
            .mark_rule(strokeDash=[2, 3], color="#7a4a1e", strokeWidth=2)
            .encode(y="y:Q")
        )
        st.altair_chart((bars + txt + r25 + r35).properties(height=300), use_container_width=True)

    st.markdown("### Here’s where the family card went")
    # Month filter — drives buckets, compare bars, drivers, and peek-inside
    _month_keys = sorted(purch["month"].dropna().unique().tolist())
    if not _month_keys:
        st.info("No charges to group yet.")
    else:
        def _black_month_label(ym: str) -> str:
            try:
                y, m = str(ym).split("-")
                return f"{month_name[int(m)]} {y}"
            except Exception:
                return str(ym)

        _default_m = this_month if this_month in _month_keys else _month_keys[-1]
        _default_idx = _month_keys.index(_default_m)
        _sel_lab = st.selectbox(
            "Pick a month",
            options=[_black_month_label(m) for m in _month_keys],
            index=_default_idx,
            key="black_where_month",
            help="Buckets, compare bars, and top stores follow this month.",
        )
        sel_month = _month_keys[
            [_black_month_label(m) for m in _month_keys].index(_sel_lab)
        ]
        # prior calendar month key for side-by-side
        try:
            _y, _m = map(int, sel_month.split("-"))
            if _m == 1:
                prior_month = f"{_y - 1}-12"
            else:
                prior_month = f"{_y}-{_m - 1:02d}"
        except Exception:
            prior_month = None

        sel_target = allowance_budget_for_month(
            int(sel_month[:4]), int(sel_month[5:7])
        )
        sel_total = float(purch.loc[purch["month"] == sel_month, "spend"].sum())
        prior_total = (
            float(purch.loc[purch["month"] == prior_month, "spend"].sum())
            if prior_month
            else 0.0
        )
        _delta = sel_total - prior_total
        _delta_txt = (
            f"{money(abs(_delta))} {'more' if _delta >= 0 else 'less'} than "
            f"{_black_month_label(prior_month)}"
            if prior_month and prior_month in _month_keys
            else "no prior month in this CSV"
        )
        st.caption(
            _md(
                f"**{_sel_lab}** · spent {money(sel_total)} vs {money(sel_target)} target "
                f"· {_delta_txt}."
            )
        )

        mix = purch[purch["month"] == sel_month].copy()
        by_bucket = (
            mix.groupby("friendly", as_index=False)["spend"]
            .sum()
            .sort_values("spend", ascending=False)
        )
        if by_bucket.empty:
            st.info(f"No charges in {_sel_lab}.")
        else:
            st.markdown(f"**Buckets in {_sel_lab}**")
            labeled_bars(
                by_bucket,
                x_col="friendly",
                y_col="spend",
                horizontal=True,
                height=max(240, 32 * len(by_bucket)),
            )

            # Two-bar compare: selected month vs prior (by bucket)
            if prior_month and prior_month in set(_month_keys):
                prior_slice = purch[purch["month"] == prior_month]
                cmp_rows = []
                all_friends = sorted(
                    set(by_bucket["friendly"])
                    | set(prior_slice["friendly"].unique())
                )
                for fr in all_friends:
                    cmp_rows.append(
                        {
                            "friendly": fr,
                            "period": _black_month_label(prior_month),
                            "spend": float(
                                prior_slice.loc[
                                    prior_slice["friendly"] == fr, "spend"
                                ].sum()
                            ),
                        }
                    )
                    cmp_rows.append(
                        {
                            "friendly": fr,
                            "period": _sel_lab,
                            "spend": float(
                                mix.loc[mix["friendly"] == fr, "spend"].sum()
                            ),
                        }
                    )
                cmp_df = pd.DataFrame(cmp_rows)
                cmp_df = cmp_df[cmp_df["spend"] > 0.5]
                if not cmp_df.empty:
                    st.markdown(
                        f"**{_black_month_label(prior_month)} vs {_sel_lab}**"
                    )
                    st.caption("Same buckets side by side — pick any month above.")
                    # order buckets by selected-month spend
                    _ord = list(by_bucket["friendly"]) + [
                        f
                        for f in all_friends
                        if f not in set(by_bucket["friendly"])
                    ]
                    labeled_bars(
                        cmp_df,
                        x_col="friendly",
                        y_col="spend",
                        color_col="period",
                        height=max(260, 28 * min(len(_ord), 12)),
                        x_sort=_ord[:12],
                        color_domain=[
                            _black_month_label(prior_month),
                            _sel_lab,
                        ],
                        color_range=["#94a3b8", "#0d9488"],
                    )

        # Drivers: selected month + full year (keep year as context)
        top_parents_sel = (
            mix.groupby("friendly", as_index=False)["spend"]
            .sum()
            .sort_values("spend", ascending=False)
            .head(5)
        )
        top_merch_sel = (
            mix.groupby("merchant", as_index=False)["spend"]
            .sum()
            .sort_values("spend", ascending=False)
            .head(5)
        )
        if year_purch.empty:
            year_for_drivers = purch
        else:
            year_for_drivers = year_purch
        top_parents_year = (
            year_for_drivers.groupby("friendly", as_index=False)["spend"]
            .sum()
            .sort_values("spend", ascending=False)
            .head(5)
        )
        top_merch_year = (
            year_for_drivers.groupby("merchant", as_index=False)["spend"]
            .sum()
            .sort_values("spend", ascending=False)
            .head(5)
        )

        st.markdown("### What drove the spending")

        def _lines(df, name_col):
            out = []
            for _, r in df.iterrows():
                out.append(f"{r[name_col]} · {money(r['spend'])}")
            return out or ["—"]

        st.markdown(_pict_card_css(), unsafe_allow_html=True)
        d1, d2 = st.columns(2)
        with d1:
            st.markdown(f"**{_sel_lab}**")
            st.markdown(
                '<div class="pict-row">'
                + _pict_card_html(
                    emoji="📁",
                    label="Top buckets",
                    value_html="<div style='font-size:1.02rem;font-weight:700;line-height:1.5;'>"
                    + "<br/>".join(_lines(top_parents_sel, "friendly"))
                    + "</div>",
                    kind="expense",
                )
                + _pict_card_html(
                    emoji="🏪",
                    label="Top stores",
                    value_html="<div style='font-size:1.02rem;font-weight:700;line-height:1.5;'>"
                    + "<br/>".join(_lines(top_merch_sel, "merchant"))
                    + "</div>",
                    kind="brokerage",
                )
                + "</div>",
                unsafe_allow_html=True,
            )
        with d2:
            st.markdown(f"**{today.year} so far**")
            st.markdown(
                '<div class="pict-row">'
                + _pict_card_html(
                    emoji="📁",
                    label="Top buckets",
                    value_html="<div style='font-size:1.02rem;font-weight:700;line-height:1.5;'>"
                    + "<br/>".join(_lines(top_parents_year, "friendly"))
                    + "</div>",
                    kind="expense",
                )
                + _pict_card_html(
                    emoji="🏪",
                    label="Top stores",
                    value_html="<div style='font-size:1.02rem;font-weight:700;line-height:1.5;'>"
                    + "<br/>".join(_lines(top_merch_year, "merchant"))
                    + "</div>",
                    kind="brokerage",
                )
                + "</div>",
                unsafe_allow_html=True,
            )

        look_opts = ["All buckets"] + list(by_bucket["friendly"]) if not by_bucket.empty else ["All buckets"]
        look = st.selectbox(
            f"Peek inside a bucket ({_sel_lab})",
            look_opts,
            key="black_bucket",
        )
        if look != "All buckets":
            drill = mix[mix["friendly"] == look].copy()
            merch = (
                drill.groupby("merchant", as_index=False)["spend"]
                .sum()
                .sort_values("spend", ascending=False)
                .head(12)
            )
            if merch.empty:
                st.caption("Nothing in that bucket that month.")
            else:
                labeled_bars(
                    merch,
                    x_col="merchant",
                    y_col="spend",
                    horizontal=True,
                    height=max(220, 26 * len(merch)),
                )

    with st.expander("Pending charges & the 750 payment", expanded=False):
        st.caption(
            _md(
                "Path B adds purchase pending to posted balance. "
                "Path A (limit − available) should land on the same ending owed. "
                "Payments listed here are already sent from checking — do not count them twice."
            )
        )
        if pending:
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "date": p.get("date"),
                            "what": p.get("label"),
                            "type": p.get("type"),
                            "amount": float(p.get("amount") or 0),
                        }
                        for p in pending
                    ]
                ).style.format({"amount": "${:,.2f}"}),
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.write("No pending snapshot saved.")

    with st.expander("Posted charges (newest first)", expanded=False):
        year_opts = ["All"] + [str(y) for y in sorted({int(y) for y in cdf["year"].unique()})]
        type_opts = ["Purchases only", "All types"]
        e1, e2 = st.columns(2)
        ysel = e1.selectbox("Year", year_opts, key="black_hist_year")
        tsel = e2.selectbox("Show", type_opts, key="black_hist_type")
        hist = cdf.copy()
        if ysel != "All":
            hist = hist[hist["year"] == int(ysel)]
        if tsel == "Purchases only":
            hist = hist[hist["is_purchase"]]
        hist = hist.sort_values("date", ascending=False)
        st.dataframe(
            pd.DataFrame(
                {
                    "date": hist["date"].dt.date.astype(str),
                    "what": hist["label"],
                    "type": hist["txn_type"],
                    "amount": hist["amount"],
                    "bucket": hist["parent"].map(_friendly_parent),
                }
            ).style.format({"amount": "${:,.2f}"}),
            use_container_width=True,
            hide_index=True,
            height=360,
        )

    st.divider()
    st.caption("Refresh the family-card CSV. This never changes the checking account numbers.")
    _render_black_card_import_box(conn, key_prefix="black_page")


# ---------- DEBT PAYDOWN ----------
elif page == "Household debt paydown":
    st.title("Household debt paydown")

    _debt_store = load_debts()
    _second = get_debt(_debt_store, "mortgage_second")
    _first = get_debt(_debt_store, "mortgage_first")
    _stu = get_debt(_debt_store, "student_loans")
    if not _second:
        st.error("Missing mortgage_second in data/debts.json")
        st.stop()

    _extra = float(_second.get("extra_principal_monthly") or 3500.0)
    _base_sched = schedule_for_debt(_second)  # baseline = $3,500 extra only, no lumps
    _payoff_lbl = (
        _base_sched.payoff_date.strftime("%b %Y")
        if _base_sched.payoff_date
        else (_base_sched.payoff_month or "—")
    )

    # ----- Priority order banner -----
    st.info(
        _md(
            "**Paydown order:** Second mortgage (now, highest rate) → "
            "Student loans (next, 5.375%) → First mortgage (lowest rate, 2.875%)."
        )
    )

    # ----- Second mortgage — focus now -----
    st.markdown("## Second mortgage — focus now")
    st.success(
        _md(
            "We're paying an extra $3,500/mo on the second mortgage to kill it by ~end Dec 2027. "
            "Use the buttons below only if you might add bonus money."
        )
    )
    st.caption(
        _md(
            "Cash twin Savings −$3,500/mo already is this extra principal — don't double-count. "
            "This page does not change the checking starting balance."
        )
    )
    st.caption(
        _md(
            f"Loan #{_second.get('loan_number') or '—'} · "
            f"{_second.get('property') or ''} · "
            f"{_second.get('borrower') or '—'}"
        )
    )

    # ----- Summary chips (baseline only) -----
    st.markdown(_pict_card_css(), unsafe_allow_html=True)
    st.markdown(
        '<div class="pict-row">'
        + _pict_card_html(
            emoji="🔥",
            label="Second mortgage balance",
            value_html=_fmt_pict_money(float(_second["current_balance"])),
            sub=f"as of {_second.get('balance_as_of') or _debt_store.get('as_of') or '—'}",
            kind="expense",
        )
        + _pict_card_html(
            emoji="📈",
            label="Rate",
            value_html=f'<span>{float(_second["annual_rate"]) * 100:.3f}%</span>',
            sub=f"Original {money(_second.get('original_balance'))}",
            kind="brokerage",
        )
        + _pict_card_html(
            emoji="💸",
            label="Regular payment",
            value_html=_fmt_pict_money(float(_second["regular_payment"]), signed="neg"),
            sub="Minimum monthly · escrow $0",
            kind="expense",
        )
        + _pict_card_html(
            emoji="🚀",
            label="Extra principal / mo",
            value_html=_fmt_pict_money(_extra, signed="neg"),
            sub="= cash twin Savings transfer",
            kind="savings",
        )
        + _pict_card_html(
            emoji="🏁",
            label="Baseline payoff",
            value_html=f"<span>{_payoff_lbl}</span>",
            sub=f"+{_extra:,.0f}/mo extra only · ~end-2027",
            kind="income",
        )
        + "</div>",
        unsafe_allow_html=True,
    )

    # ----- Burn-down chart (baseline) -----
    st.markdown("### Your 3,500 / mo plan (baseline)")
    st.caption(
        _md(
            f"Balance over months with payment {money(_second['regular_payment'])} "
            f"+ extra {money(_extra)}/mo — no bonus lumps."
        )
    )
    _series = balance_series(_base_sched)
    if _series:
        _bdf = pd.DataFrame(_series)
        _chart_df = _bdf.set_index("month")[["balance"]]
        try:
            import altair as alt

            _line = (
                alt.Chart(_bdf)
                .mark_area(opacity=0.35, line=True, color="#c45c26")
                .encode(
                    x=alt.X("month:N", title="Month", sort=None),
                    y=alt.Y("balance:Q", title="Balance", axis=alt.Axis(format="$,.0f")),
                    tooltip=[
                        "month",
                        alt.Tooltip("balance:Q", format="$,.2f"),
                        alt.Tooltip("interest:Q", format="$,.2f"),
                        alt.Tooltip("principal_regular:Q", format="$,.2f"),
                        alt.Tooltip("principal_extra:Q", format="$,.2f"),
                    ],
                )
                .properties(height=320)
            )
            st.altair_chart(_line, use_container_width=True)
        except Exception:
            st.line_chart(_chart_df, height=320)

        with st.expander("Month-by-month payoff detail", expanded=False):
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "Month": r.month,
                            "Opening": r.opening_balance,
                            "Interest": r.interest,
                            "Prin (min)": r.principal_regular,
                            "Prin (extra)": r.principal_extra,
                            "Bonus": r.principal_lump,
                            "Closing": r.closing_balance,
                        }
                        for r in _base_sched.rows
                    ]
                ),
                use_container_width=True,
                hide_index=True,
            )
        _cps = _second.get("excel_checkpoints") or {}
        with st.expander("Does this still match my old Excel?", expanded=False):
            st.caption(
                "Optional check for nerds — you can ignore this. "
                "It only confirms the burn-down still lines up with your old spreadsheet."
            )
            _cap = excel_checkpoint_caption(_base_sched, _cps)
            # Short status line only; hide the dense model-vs-Excel Δ list unless asked
            if "within" in _cap.lower() or "matches" in _cap.lower():
                st.success("Yes — still matches your Excel track (within about a dollar).")
            else:
                st.info(_md(_cap.split(":")[0] if ":" in _cap else _cap))
            show_detail = st.checkbox(
                "Show month-by-month Excel vs model",
                value=False,
                key="debt_excel_detail",
            )
            if show_detail and _cps:
                by_month = {r.month: r.closing_balance for r in _base_sched.rows}
                rows = []
                for ym, excel_bal in _cps.items():
                    model = by_month.get(ym)
                    if model is None:
                        continue
                    rows.append(
                        {
                            "Month": ym,
                            "This app": float(model),
                            "Your Excel": float(excel_bal),
                            "Difference": float(model) - float(excel_bal),
                        }
                    )
                if rows:
                    st.dataframe(
                        pd.DataFrame(rows).style.format(
                            {
                                "This app": "${:,.2f}",
                                "Your Excel": "${:,.2f}",
                                "Difference": "${:+,.2f}",
                            }
                        ),
                        use_container_width=True,
                        hide_index=True,
                    )

    # ----- What if I add bonus money? -----
    st.markdown("### What if I add bonus money?")
    st.caption(
        _md(
            "Optional. Your plan already includes the $3,500/mo extra. "
            "These buttons only add one-time bonus payments on top — "
            "the $24k figure is an example bonus, not a balance you owe."
        )
    )

    _def_sc = _debt_store.get("default_scenario") or {}
    _def_lump = float(_def_sc.get("lump_sum") or 24000)
    _def_lump_d = _def_sc.get("lump_date") or "2027-01-01"
    try:
        _def_lump_date = date.fromisoformat(str(_def_lump_d)[:10])
    except ValueError:
        _def_lump_date = date(2027, 1, 1)

    _plan_choice = st.radio(
        "Pick a plan",
        [
            "A) Just my 3,500 / month plan",
            "B) 3,500 / month + one bonus",
            "C) 3,500 / month + two bonuses",
        ],
        index=0,
        key="debt_bonus_plan",
        horizontal=False,
        help="Baseline never includes bonus lumps. B/C are what-ifs only.",
    )

    _scenario_lumps: list = []
    _scenario_label = "Just my 3,500 / month plan"

    if _plan_choice.startswith("B)"):
        _b_preset = st.radio(
            "One bonus — quick pick",
            [
                "10k bonus",
                "24k example bonus",
                "Custom",
            ],
            index=1,
            key="debt_one_bonus_preset",
            horizontal=True,
            help="\\$24k is an example bonus for planning — not money you currently owe.",
        )
        if _b_preset == "10k bonus":
            _b_amt, _b_dt = 10000.0, date(2027, 1, 1)
        elif _b_preset == "24k example bonus":
            _b_amt, _b_dt = float(_def_lump), _def_lump_date
        else:
            _b_amt, _b_dt = float(_def_lump), _def_lump_date

        bc1, bc2 = st.columns(2)
        with bc1:
            _b_amt = st.number_input(
                "Bonus amount",
                min_value=0.0,
                value=float(_b_amt),
                step=1000.0,
                format="%.2f",
                key=f"debt_one_bonus_amt_{_b_preset}",
                help="Example bonus / March bonus / tax refund — not a loan balance.",
            )
        with bc2:
            _b_dt = st.date_input(
                "Bonus date",
                value=_b_dt,
                key=f"debt_one_bonus_date_{_b_preset}",
            )
        if _b_amt > 0:
            _scenario_lumps = [{"amount": float(_b_amt), "date": _b_dt}]
            _scenario_label = f"3,500 / mo + {money(_b_amt)} bonus ({parse_lump_date(_b_dt)})"

    elif _plan_choice.startswith("C)"):
        _c_preset = st.radio(
            "Two bonuses — quick pick",
            [
                "Jan 12k + Mar 12k",
                "Jan 24k example + Mar 10k",
                "Custom",
            ],
            index=0,
            key="debt_two_bonus_preset",
            horizontal=True,
            help="Two example bonuses on top of the 3,500/mo plan.",
        )
        if _c_preset == "Jan 12k + Mar 12k":
            _c1_amt, _c1_dt = 12000.0, date(2027, 1, 1)
            _c2_amt, _c2_dt = 12000.0, date(2027, 3, 1)
        elif _c_preset == "Jan 24k example + Mar 10k":
            _c1_amt, _c1_dt = 24000.0, date(2027, 1, 1)
            _c2_amt, _c2_dt = 10000.0, date(2027, 3, 1)
        else:
            _c1_amt, _c1_dt = 12000.0, date(2027, 1, 1)
            _c2_amt, _c2_dt = 12000.0, date(2027, 3, 1)

        st.markdown("**Bonus 1**")
        c1a, c1b = st.columns(2)
        with c1a:
            _c1_amt = st.number_input(
                "Bonus 1 amount",
                min_value=0.0,
                value=float(_c1_amt),
                step=1000.0,
                format="%.2f",
                key=f"debt_two_b1_amt_{_c_preset}",
            )
        with c1b:
            _c1_dt = st.date_input(
                "Bonus 1 date",
                value=_c1_dt,
                key=f"debt_two_b1_date_{_c_preset}",
            )
        st.markdown("**Bonus 2**")
        c2a, c2b = st.columns(2)
        with c2a:
            _c2_amt = st.number_input(
                "Bonus 2 amount",
                min_value=0.0,
                value=float(_c2_amt),
                step=1000.0,
                format="%.2f",
                key=f"debt_two_b2_amt_{_c_preset}",
            )
        with c2b:
            _c2_dt = st.date_input(
                "Bonus 2 date",
                value=_c2_dt,
                key=f"debt_two_b2_date_{_c_preset}",
            )
        _scenario_lumps = []
        if _c1_amt > 0:
            _scenario_lumps.append({"amount": float(_c1_amt), "date": _c1_dt})
        if _c2_amt > 0:
            _scenario_lumps.append({"amount": float(_c2_amt), "date": _c2_dt})
        if _scenario_lumps:
            _bits = [
                f"{money(x['amount'])} ({parse_lump_date(x['date'])})"
                for x in _scenario_lumps
            ]
            _scenario_label = "3,500 / mo + " + " + ".join(_bits)

    # Build scenario schedule (baseline if no lumps / plan A)
    if _scenario_lumps:
        _sc_sched = schedule_for_debt(_second, lumps=_scenario_lumps)
    else:
        _sc_sched = _base_sched
    _cmp = compare_schedules(_base_sched, _sc_sched)

    def _fmt_payoff_mo(ym):
        if not ym:
            return "—"
        try:
            y, m = int(ym[:4]), int(ym[5:7])
            return date(y, m, 1).strftime("%b %Y")
        except Exception:
            return ym

    _base_pay_h = _fmt_payoff_mo(_cmp.get("baseline_payoff_month"))
    _sc_pay_h = _fmt_payoff_mo(_cmp.get("scenario_payoff_month"))
    _months_saved = _cmp.get("months_saved")
    _int_saved = _cmp.get("interest_saved") or 0.0

    # Side-by-side compare card
    st.markdown("#### Side-by-side")
    if not _scenario_lumps:
        st.info(
            _md(
                f"**Baseline:** paid off {_base_pay_h}. "
                "Pick B or C above only if you might add bonus money."
            )
        )
    else:
        if _months_saved and _months_saved > 0:
            _plain = (
                f"Paid off {int(_months_saved)} months sooner · "
                f"saves about {money(_int_saved)} in interest"
            )
        elif _months_saved == 0:
            _plain = f"Same payoff month · interest change {money(_int_saved)}"
        else:
            _plain = (
                f"This plan payoff {_sc_pay_h} vs baseline {_base_pay_h} · "
                f"interest change {money(_int_saved)}"
            )
        st.success(_md(_plain))

    cm1, cm2, cm3, cm4 = st.columns(4)
    cm1.metric("Baseline payoff", _base_pay_h)
    cm2.metric(
        "This plan payoff",
        _sc_pay_h if _scenario_lumps else _base_pay_h,
        delta=(
            f"−{int(_months_saved)} mo"
            if _scenario_lumps and _months_saved
            else None
        ),
        delta_color="normal",
    )
    cm3.metric(
        "Months faster",
        (
            f"{int(_months_saved)}"
            if _scenario_lumps and _months_saved is not None
            else "—"
        ),
    )
    cm4.metric(
        "Interest saved",
        money(_int_saved) if _scenario_lumps else "—",
        help=_md(
            f"Baseline interest {money(_cmp.get('baseline_total_interest'))} → "
            f"this plan {money(_cmp.get('scenario_total_interest'))}"
        ),
    )
    if _scenario_lumps:
        st.caption(_md(f"Comparing: **{_scenario_label}** vs baseline (3,500 / mo only)."))

    # Overlay burn-down when scenario differs
    if _scenario_lumps and _series:
        _sc_series = balance_series(_sc_sched)
        _cmp_df = pd.DataFrame(
            {
                "Baseline (3,500 / mo)": {r["month"]: r["balance"] for r in _series},
                "This plan": {r["month"]: r["balance"] for r in _sc_series},
            }
        ).sort_index()
        all_months = sorted(set(_cmp_df.index))
        _cmp_df = _cmp_df.reindex(all_months).fillna(0.0)
        st.markdown("##### Baseline vs this plan")
        try:
            import altair as alt

            _melt = _cmp_df.reset_index().rename(columns={"index": "month"})
            _long = _melt.melt("month", var_name="Plan", value_name="balance")
            _overlay = (
                alt.Chart(_long)
                .mark_line(strokeWidth=2.5)
                .encode(
                    x=alt.X("month:N", title="Month", sort=None),
                    y=alt.Y("balance:Q", title="Balance", axis=alt.Axis(format="$,.0f")),
                    color=alt.Color(
                        "Plan:N",
                        scale=alt.Scale(
                            domain=["Baseline (3,500 / mo)", "This plan"],
                            range=["#c45c26", "#2a6f97"],
                        ),
                    ),
                    tooltip=[
                        "month",
                        "Plan",
                        alt.Tooltip("balance:Q", format="$,.2f"),
                    ],
                )
                .properties(height=280)
            )
            st.altair_chart(_overlay, use_container_width=True)
        except Exception:
            st.line_chart(_cmp_df, height=280)

        with st.expander("Month-by-month payoff detail (this plan)", expanded=False):
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "Month": r.month,
                            "Opening": r.opening_balance,
                            "Interest": r.interest,
                            "Prin (min)": r.principal_regular,
                            "Prin (extra)": r.principal_extra,
                            "Bonus": r.principal_lump,
                            "Closing": r.closing_balance,
                        }
                        for r in _sc_sched.rows
                    ]
                ),
                use_container_width=True,
                hide_index=True,
            )

    # ----- After this debt -----
    st.markdown("### After this debt")
    _stu_bal_hint = float((_stu or {}).get("current_balance") or 98000.00)
    st.info(
        _md(
            f"When the second is gone (~end 2027) → point the $3,500/mo extra at "
            f"**student loans** next (~{money(_stu_bal_hint)}, 5.375% — higher than the first) → "
            "then the first mortgage (2.875%, lowest rate). "
            "Cash twin Savings rule stays as-is until you change it."
        )
    )

    st.divider()

    # =========================================================================
    # Student loans — next after the second (higher rate than first)
    # =========================================================================
    st.markdown("## Student loans — next (higher rate)")

    if not _stu or _stu.get("current_balance") is None or _stu.get("status") == "placeholder":
        st.warning("Student loans not loaded — check data/debts.json student_loans.")
    else:
        _s_bal = float(_stu["current_balance"])
        _s_rate = float(_stu["annual_rate"])
        _s_pay = float(_stu["regular_payment"])
        _s_extra_default_start = _stu.get("extra_start_month") or "2028-01"
        _s_groups = _stu.get("groups") or _stu.get("loans") or []
        _s_am = next((g for g in _s_groups if g.get("id") == "AM"), None)
        _s_an = next((g for g in _s_groups if g.get("id") == "AN"), None)
        _s_base_sched = schedule_for_debt(_stu, extra_principal=0.0)
        _s_base_pay_lbl = (
            _s_base_sched.payoff_date.strftime("%b %Y")
            if _s_base_sched.payoff_date
            else (_s_base_sched.payoff_month or "—")
        )
        _s_redirect_sched = schedule_for_debt(
            _stu,
            extra_principal=3500.0,
            extra_start_month=_s_extra_default_start,
        )
        _s_redirect_lbl = (
            _s_redirect_sched.payoff_date.strftime("%b %Y")
            if _s_redirect_sched.payoff_date
            else (_s_redirect_sched.payoff_month or "—")
        )

        st.success(
            _md(
                f"EduServe student loans ~{_s_bal/1000:.1f}k at {_s_rate * 100:.3f}% "
                f"(Standard Repayment, due day {_stu.get('payment_day') or 6}). "
                "After the second is paid (~end 2027), this is usually the next place for the "
                "3,500 / mo extra — higher rate than the first mortgage."
            )
        )
        st.caption(
            _md(
                f"Account {_stu.get('account_number') or '—'} · {_stu.get('servicer') or 'EduServe'} · "
                f"{_stu.get('repayment_plan') or 'Standard Repayment'} · "
                f"{_stu.get('borrower') or '—'} · "
                f"Last payment {money(float((_stu.get('last_payment') or {}).get('amount') or _s_pay))} "
                f"on {(_stu.get('last_payment') or {}).get('date') or '—'}"
            )
        )
        st.caption(
            _md(
                "Cash twin already budgets Student Loans −$650.00/mo — don't double-count. "
                "This page is debt analytics only."
            )
        )
        if _stu.get("goal_narrative"):
            st.caption(_md(_stu["goal_narrative"]))

        # Chips
        st.markdown(_pict_card_css(), unsafe_allow_html=True)
        _s_am_sub = (
            f"AM {money(float(_s_am['outstanding']))} · AN {money(float(_s_an['outstanding']))}"
            if _s_am and _s_an
            else "DIRECT CONSOL groups"
        )
        _s_chip_html = (
            '<div class="pict-row">'
            + _pict_card_html(
                emoji="🎓",
                label="Student loans balance",
                value_html=_fmt_pict_money(_s_bal),
                sub=f"as of {_stu.get('balance_as_of') or '—'} · {_s_am_sub}",
                kind="expense",
            )
            + _pict_card_html(
                emoji="📈",
                label="Rate",
                value_html=f'<span>{_s_rate * 100:.3f}%</span>',
                sub="Effective · regulatory 6.375%",
                kind="brokerage",
            )
            + _pict_card_html(
                emoji="💸",
                label="Regular payment",
                value_html=_fmt_pict_money(_s_pay, signed="neg"),
                sub=(
                    f"AM {money(float(_s_am['payment']))} + AN {money(float(_s_an['payment']))}"
                    if _s_am and _s_an
                    else "Standard Repayment"
                ),
                kind="expense",
            )
            + _pict_card_html(
                emoji="🏁",
                label="Baseline payoff",
                value_html=f"<span>{_s_base_pay_lbl}</span>",
                sub="Minimum only",
                kind="income",
            )
            + _pict_card_html(
                emoji="⏭️",
                label="If +3,500/mo after second",
                value_html=f"<span>{_s_redirect_lbl}</span>",
                sub=f"Extra starts {_s_extra_default_start}",
                kind="savings",
            )
            + "</div>"
        )
        st.markdown(_s_chip_html, unsafe_allow_html=True)

        if _s_am and _s_an:
            st.caption(
                _md(
                    f"Split: **AM** {money(float(_s_am['outstanding']))} "
                    f"(pay {money(float(_s_am['payment']))}/mo) · "
                    f"**AN** {money(float(_s_an['outstanding']))} "
                    f"(pay {money(float(_s_an['payment']))}/mo) — same 5.375% effective rate."
                )
            )

        st.info(
            _md(
                "Paying extra here vs the first mortgage: student rate 5.375% vs first 2.875%, "
                "so after the second, students usually win on interest math."
            )
        )

        # Burn-down baseline (min only) — combined
        st.markdown("### Your minimum plan (baseline)")
        st.caption(
            _md(
                f"Combined balance over months with payment {money(_s_pay)}/mo only — no extra principal. "
                "AM + AN modeled as one loan at 5.375%."
            )
        )
        _s_series = balance_series(_s_base_sched)
        if _s_series:
            _s_bdf = pd.DataFrame(_s_series)
            _s_chart_df = _s_bdf.set_index("month")[["balance"]]
            try:
                import altair as alt

                _s_line = (
                    alt.Chart(_s_bdf)
                    .mark_area(opacity=0.35, line=True, color="#5c4d7a")
                    .encode(
                        x=alt.X("month:N", title="Month", sort=None),
                        y=alt.Y("balance:Q", title="Balance", axis=alt.Axis(format="$,.0f")),
                        tooltip=[
                            "month",
                            alt.Tooltip("balance:Q", format="$,.2f"),
                            alt.Tooltip("interest:Q", format="$,.2f"),
                            alt.Tooltip("principal_regular:Q", format="$,.2f"),
                            alt.Tooltip("principal_extra:Q", format="$,.2f"),
                        ],
                    )
                    .properties(height=320)
                )
                st.altair_chart(_s_line, use_container_width=True)
            except Exception:
                st.line_chart(_s_chart_df, height=320)

            with st.expander("Month-by-month payoff detail (students · baseline)", expanded=False):
                st.dataframe(
                    pd.DataFrame(
                        [
                            {
                                "Month": r.month,
                                "Opening": r.opening_balance,
                                "Interest": r.interest,
                                "Prin (min)": r.principal_regular,
                                "Prin (extra)": r.principal_extra,
                                "Bonus": r.principal_lump,
                                "Closing": r.closing_balance,
                            }
                            for r in _s_base_sched.rows
                        ]
                    ),
                    use_container_width=True,
                    hide_index=True,
                )

        # What-if A/B/C
        st.markdown("### What if I add extra?")
        st.caption(
            _md(
                "Optional what-ifs. Default: keep minimum until the second is gone, "
                "then add whatever monthly extra you want starting Jan 2028. "
                "Toggle “start extra now” only if you want to try overlapping with the second."
            )
        )

        _s_plan = st.radio(
            "Pick a student-loan plan",
            [
                "A) Minimum only",
                "B) Add a monthly extra (after second)",
                "C) Monthly extra + one/two bonus lumps",
            ],
            index=0,
            key="debt_stu_plan",
            horizontal=False,
            help="Baseline is minimum payment. B/C: type any monthly extra in the box (starts blank).",
        )

        try:
            _s_def_y, _s_def_m = int(_s_extra_default_start[:4]), int(_s_extra_default_start[5:7])
            _s_def_start_date = date(_s_def_y, _s_def_m, 1)
        except Exception:
            _s_def_start_date = date(2028, 1, 1)

        _s_extra_from = _s_extra_default_start
        _s_extra_from_lbl = _s_extra_default_start
        _s_start_now = False
        if not _s_plan.startswith("A)"):
            _s_start_now = st.checkbox(
                "Start extra now (overlap with second) — off by default",
                value=False,
                key="debt_stu_extra_now",
                help="When off, extra starts in the month below (default 2028-01).",
            )
            if _s_start_now:
                _s_extra_from = ""
                _s_extra_from_lbl = "now (from projection start)"
            else:
                _s_extra_start_in = st.date_input(
                    "Extra starts (month)",
                    value=_s_def_start_date,
                    key="debt_stu_extra_start",
                    help="Default Jan 2028 — after second ~Dec 2027 payoff.",
                )
                _s_extra_from = f"{_s_extra_start_in.year}-{_s_extra_start_in.month:02d}"
                _s_extra_from_lbl = _s_extra_from

        _s_scenario_lumps: list = []
        _s_extra_amt = 0.0
        _s_scenario_label = "Minimum only"

        if _s_plan.startswith("A)"):
            _s_extra_amt = 0.0
            _s_scenario_label = "Minimum only"
        else:
            _s_extra_raw = st.text_input(
                "Monthly extra amount",
                value="",
                placeholder="Type any amount (e.g. 2000)",
                key="debt_stu_extra_amt",
                help="Leave blank for 0. No default — enter whatever extra you want to model.",
            )
            try:
                _s_extra_amt = float(str(_s_extra_raw).replace(",", "").replace("$", "").strip() or 0)
            except ValueError:
                _s_extra_amt = 0.0
                st.caption("Enter a number for monthly extra (e.g. 2000).")
            if _s_extra_amt > 0:
                _s_scenario_label = f"{_s_extra_amt:,.0f} / mo extra from {_s_extra_from_lbl}"
            else:
                _s_scenario_label = f"No monthly extra yet (from {_s_extra_from_lbl})"
        if _s_plan.startswith("C)"):
            _s_c_preset = st.radio(
                "Bonuses on top of the monthly extra — quick pick",
                [
                    "One 24k example bonus",
                    "Jan 12k + Mar 12k (of start year)",
                    "Custom one or two",
                ],
                index=0,
                key="debt_stu_bonus_preset",
                horizontal=False,
                help="Bonus months default relative to the extra-start year.",
            )
            _s_anchor_y = (
                int((_s_extra_from or "2028-01")[:4])
                if not _s_start_now
                else 2028
            )
            if _s_c_preset.startswith("One 24k"):
                _sc1_amt, _sc1_dt = 24000.0, date(_s_anchor_y, 1, 1)
                _sc2_amt, _sc2_dt = 0.0, date(_s_anchor_y, 3, 1)
                _s_show_two = False
            elif _s_c_preset.startswith("Jan 12k"):
                _sc1_amt, _sc1_dt = 12000.0, date(_s_anchor_y, 1, 1)
                _sc2_amt, _sc2_dt = 12000.0, date(_s_anchor_y, 3, 1)
                _s_show_two = True
            else:
                _sc1_amt, _sc1_dt = 24000.0, date(_s_anchor_y, 1, 1)
                _sc2_amt, _sc2_dt = 0.0, date(_s_anchor_y, 3, 1)
                _s_show_two = True

            st.markdown("**Bonus 1**")
            sc1a, sc1b = st.columns(2)
            with sc1a:
                _sc1_amt = st.number_input(
                    "Bonus 1 amount",
                    min_value=0.0,
                    value=float(_sc1_amt),
                    step=1000.0,
                    format="%.2f",
                    key=f"debt_stu_b1_amt_{_s_c_preset}",
                    help="Example bonus — not a balance owed.",
                )
            with sc1b:
                _sc1_dt = st.date_input(
                    "Bonus 1 date",
                    value=_sc1_dt,
                    key=f"debt_stu_b1_date_{_s_c_preset}",
                )
            if _s_show_two:
                st.markdown("**Bonus 2 (optional)**")
                sc2a, sc2b = st.columns(2)
                with sc2a:
                    _sc2_amt = st.number_input(
                        "Bonus 2 amount",
                        min_value=0.0,
                        value=float(_sc2_amt),
                        step=1000.0,
                        format="%.2f",
                        key=f"debt_stu_b2_amt_{_s_c_preset}",
                    )
                with sc2b:
                    _sc2_dt = st.date_input(
                        "Bonus 2 date",
                        value=_sc2_dt,
                        key=f"debt_stu_b2_date_{_s_c_preset}",
                    )
            _s_scenario_lumps = []
            if _sc1_amt > 0:
                _s_scenario_lumps.append({"amount": float(_sc1_amt), "date": _sc1_dt})
            if _s_show_two and _sc2_amt > 0:
                _s_scenario_lumps.append({"amount": float(_sc2_amt), "date": _sc2_dt})
            _s_bits = [
                f"{money(x['amount'])} ({parse_lump_date(x['date'])})"
                for x in _s_scenario_lumps
            ]
            if _s_extra_amt > 0:
                _s_scenario_label = f"{_s_extra_amt:,.0f} / mo from {_s_extra_from_lbl}"
            else:
                _s_scenario_label = f"No monthly extra yet (from {_s_extra_from_lbl})"
            if _s_bits:
                _s_scenario_label += " + " + " + ".join(_s_bits)

        if _s_extra_amt > 0 or _s_scenario_lumps:
            _s_sc_sched = schedule_for_debt(
                _stu,
                extra_principal=_s_extra_amt,
                extra_start_month=_s_extra_from,
                lumps=_s_scenario_lumps or None,
            )
        else:
            _s_sc_sched = _s_base_sched
        _s_cmp = compare_schedules(_s_base_sched, _s_sc_sched)

        def _fmt_payoff_mo_s(ym):
            if not ym:
                return "—"
            try:
                y, m = int(ym[:4]), int(ym[5:7])
                return date(y, m, 1).strftime("%b %Y")
            except Exception:
                return ym

        _s_base_pay_h = _fmt_payoff_mo_s(_s_cmp.get("baseline_payoff_month"))
        _s_sc_pay_h = _fmt_payoff_mo_s(_s_cmp.get("scenario_payoff_month"))
        _s_months_saved = _s_cmp.get("months_saved")
        _s_int_saved = _s_cmp.get("interest_saved") or 0.0
        _s_has_scenario = bool(_s_extra_amt > 0 or _s_scenario_lumps)

        st.markdown("#### Side-by-side")
        if not _s_has_scenario:
            st.info(
                _md(
                    f"**Baseline:** paid off {_s_base_pay_h} on minimum only. "
                    "Pick B or C to try redirecting 3,500 / mo after the second."
                )
            )
        else:
            if _s_months_saved and _s_months_saved > 0:
                _s_plain = (
                    f"Paid off {int(_s_months_saved)} months sooner · "
                    f"saves about {money(_s_int_saved)} in interest"
                )
            elif _s_months_saved == 0:
                _s_plain = f"Same payoff month · interest change {money(_s_int_saved)}"
            else:
                _s_plain = (
                    f"This plan payoff {_s_sc_pay_h} vs baseline {_s_base_pay_h} · "
                    f"interest change {money(_s_int_saved)}"
                )
            st.success(_md(_s_plain))

        sm1, sm2, sm3, sm4 = st.columns(4)
        sm1.metric("Baseline payoff", _s_base_pay_h)
        sm2.metric(
            "This plan payoff",
            _s_sc_pay_h if _s_has_scenario else _s_base_pay_h,
            delta=(
                f"−{int(_s_months_saved)} mo"
                if _s_has_scenario and _s_months_saved
                else None
            ),
            delta_color="normal",
        )
        sm3.metric(
            "Months faster",
            (
                f"{int(_s_months_saved)}"
                if _s_has_scenario and _s_months_saved is not None
                else "—"
            ),
        )
        sm4.metric(
            "Interest saved",
            money(_s_int_saved) if _s_has_scenario else "—",
            help=_md(
                f"Baseline interest {money(_s_cmp.get('baseline_total_interest'))} → "
                f"this plan {money(_s_cmp.get('scenario_total_interest'))}"
            ),
        )
        if _s_has_scenario:
            st.caption(_md(f"Comparing: **{_s_scenario_label}** vs baseline (minimum only)."))

        if _s_has_scenario and _s_series:
            _s_sc_series = balance_series(_s_sc_sched)
            _s_cmp_df = pd.DataFrame(
                {
                    "Baseline (min only)": {r["month"]: r["balance"] for r in _s_series},
                    "This plan": {r["month"]: r["balance"] for r in _s_sc_series},
                }
            ).sort_index()
            _s_all_months = sorted(set(_s_cmp_df.index))
            _s_cmp_df = _s_cmp_df.reindex(_s_all_months).fillna(0.0)
            st.markdown("##### Baseline vs this plan")
            try:
                import altair as alt

                _s_melt = _s_cmp_df.reset_index().rename(columns={"index": "month"})
                _s_long = _s_melt.melt("month", var_name="Plan", value_name="balance")
                _s_overlay = (
                    alt.Chart(_s_long)
                    .mark_line(strokeWidth=2.5)
                    .encode(
                        x=alt.X("month:N", title="Month", sort=None),
                        y=alt.Y("balance:Q", title="Balance", axis=alt.Axis(format="$,.0f")),
                        color=alt.Color(
                            "Plan:N",
                            scale=alt.Scale(
                                domain=["Baseline (min only)", "This plan"],
                                range=["#5c4d7a", "#c45c26"],
                            ),
                        ),
                        tooltip=[
                            "month",
                            "Plan",
                            alt.Tooltip("balance:Q", format="$,.2f"),
                        ],
                    )
                    .properties(height=280)
                )
                st.altair_chart(_s_overlay, use_container_width=True)
            except Exception:
                st.line_chart(_s_cmp_df, height=280)

            with st.expander("Month-by-month payoff detail (students · this plan)", expanded=False):
                st.dataframe(
                    pd.DataFrame(
                        [
                            {
                                "Month": r.month,
                                "Opening": r.opening_balance,
                                "Interest": r.interest,
                                "Prin (min)": r.principal_regular,
                                "Prin (extra)": r.principal_extra,
                                "Bonus": r.principal_lump,
                                "Closing": r.closing_balance,
                            }
                            for r in _s_sc_sched.rows
                        ]
                    ),
                    use_container_width=True,
                    hide_index=True,
                )

        with st.expander("Refresh student-loan balance (screenshots)", expanded=False):
            st.caption(
                _md(
                    "Saved to the debts file — does not touch checking start balance or mortgages. "
                    "Cash twin Student Loans rule stays −$650.00/mo."
                )
            )
            with st.form("debt_stu_refresh"):
                snb = st.number_input(
                    "Current balance (combined)",
                    value=float(_stu["current_balance"]),
                    step=100.0,
                    format="%.2f",
                    key="debt_stu_bal_refresh",
                )
                snas = st.text_input(
                    "As of",
                    value=_stu.get("balance_as_of") or "",
                    key="debt_stu_asof_refresh",
                )
                snpay = st.number_input(
                    "Regular payment",
                    value=float(_stu.get("regular_payment") or 0),
                    step=10.0,
                    format="%.2f",
                    key="debt_stu_pay_refresh",
                )
                snrate = st.number_input(
                    "Annual rate (e.g. 0.05500)",
                    value=float(_stu.get("annual_rate") or 0.05500),
                    step=0.00001,
                    format="%.5f",
                    key="debt_stu_rate_refresh",
                )
                if st.form_submit_button("Save student-loan snapshot"):
                    store = load_debts()
                    d = get_debt(store, "student_loans")
                    if d is not None:
                        d["current_balance"] = float(snb)
                        d["status"] = "active"
                        if snas.strip():
                            d["balance_as_of"] = snas.strip()
                        d["regular_payment"] = float(snpay)
                        d["annual_rate"] = float(snrate)
                        save_debts(store)
                        st.success("Saved to data/debts.json")
                        st.rerun()


    st.divider()

    # =========================================================================
    # First mortgage — lowest rate (after students)
    # =========================================================================
    st.markdown("## First mortgage — lowest rate (last)")

    if not _first or _first.get("current_balance") is None or _first.get("status") == "placeholder":
        st.warning("First mortgage not loaded — check data/debts.json mortgage_first.")
    else:
        _f_bal = float(_first["current_balance"])
        _f_rate = float(_first["annual_rate"])
        _f_pi = float(_first["regular_payment"])  # P&I only
        _f_escrow = float(_first.get("escrow") or 0.0)
        _f_total_pay = float(_first.get("total_payment") or (_f_pi + _f_escrow))
        _f_escrow_bal = _first.get("escrow_balance")
        _f_extra_default_start = _first.get("extra_start_month") or "2028-01"
        _f_base_sched = schedule_for_debt(_first, extra_principal=0.0)  # min P&I only
        _f_base_pay_lbl = (
            _f_base_sched.payoff_date.strftime("%b %Y")
            if _f_base_sched.payoff_date
            else (_f_base_sched.payoff_month or "—")
        )

        # Optional "if +$3,500 after second" chip schedule
        _f_redirect_sched = schedule_for_debt(
            _first,
            extra_principal=3500.0,
            extra_start_month=_f_extra_default_start,
        )
        _f_redirect_lbl = (
            _f_redirect_sched.payoff_date.strftime("%b %Y")
            if _f_redirect_sched.payoff_date
            else (_f_redirect_sched.payoff_month or "—")
        )

        st.success(
            _md(
                f"First mortgage ~{_f_bal/1000:.1f}k at {_f_rate * 100:.3f}% — lowest rate on the stack. "
                "After the second (~end 2027), student loans (5.375%) usually win on interest math first; "
                "try redirecting the 3,500 / mo extra here only if you prefer this debt."
            )
        )
        st.caption(
            _md(
                f"{_first.get('property') or ''} · {_first.get('borrower') or '—'} · "
                f"Closing {_first.get('closing_date') or '—'} · Maturity {_first.get('maturity_date') or '—'} · "
                f"Next payment {_first.get('next_payment_date') or '—'}"
            )
        )
        st.caption(
            _md(
                f"Total payment {_first.get('total_payment') and money(_f_total_pay)} = "
                f"P&I {money(_f_pi)} + escrow {money(_f_escrow)} "
                "(amortize P&I only; escrow is taxes/insurance, not principal)."
            )
        )
        if _first.get("goal_narrative"):
            st.caption(_md(_first["goal_narrative"]))

        # Chips
        st.markdown(_pict_card_css(), unsafe_allow_html=True)
        _f_chip_html = (
            '<div class="pict-row">'
            + _pict_card_html(
                emoji="🏠",
                label="First mortgage balance",
                value_html=_fmt_pict_money(_f_bal),
                sub=f"as of {_first.get('balance_as_of') or '—'}",
                kind="expense",
            )
            + _pict_card_html(
                emoji="📉",
                label="Rate",
                value_html=f'<span>{_f_rate * 100:.3f}%</span>',
                sub=f"Original {money(_first.get('original_balance'))} · low rate",
                kind="brokerage",
            )
            + _pict_card_html(
                emoji="💸",
                label="P&I payment",
                value_html=_fmt_pict_money(_f_pi, signed="neg"),
                sub=f"Total w/ escrow {money(_f_total_pay)}",
                kind="expense",
            )
            + _pict_card_html(
                emoji="🧾",
                label="Escrow (info)",
                value_html=_fmt_pict_money(_f_escrow, signed="neg"),
                sub=(
                    f"Balance {money(float(_f_escrow_bal))} · not principal"
                    if _f_escrow_bal is not None
                    else "Monthly · not amortized as principal"
                ),
                kind="brokerage",
            )
            + _pict_card_html(
                emoji="🏁",
                label="Baseline payoff",
                value_html=f"<span>{_f_base_pay_lbl}</span>",
                sub="Minimum P&I only",
                kind="income",
            )
            + _pict_card_html(
                emoji="⏭️",
                label="If +3,500/mo after second",
                value_html=f"<span>{_f_redirect_lbl}</span>",
                sub=f"Extra starts {_f_extra_default_start}",
                kind="savings",
            )
            + "</div>"
        )
        st.markdown(_f_chip_html, unsafe_allow_html=True)

        # Burn-down baseline (min only)
        st.markdown("### Your minimum plan (baseline)")
        st.caption(
            _md(
                f"Balance over months with P&I {money(_f_pi)}/mo only — no extra principal. "
                f"Escrow {money(_f_escrow)} is separate and not shown here."
            )
        )
        _f_series = balance_series(_f_base_sched)
        if _f_series:
            _f_bdf = pd.DataFrame(_f_series)
            _f_chart_df = _f_bdf.set_index("month")[["balance"]]
            try:
                import altair as alt

                _f_line = (
                    alt.Chart(_f_bdf)
                    .mark_area(opacity=0.35, line=True, color="#2a6f97")
                    .encode(
                        x=alt.X("month:N", title="Month", sort=None),
                        y=alt.Y("balance:Q", title="Balance", axis=alt.Axis(format="$,.0f")),
                        tooltip=[
                            "month",
                            alt.Tooltip("balance:Q", format="$,.2f"),
                            alt.Tooltip("interest:Q", format="$,.2f"),
                            alt.Tooltip("principal_regular:Q", format="$,.2f"),
                            alt.Tooltip("principal_extra:Q", format="$,.2f"),
                        ],
                    )
                    .properties(height=320)
                )
                st.altair_chart(_f_line, use_container_width=True)
            except Exception:
                st.line_chart(_f_chart_df, height=320)

            with st.expander("Month-by-month payoff detail (first · baseline)", expanded=False):
                st.dataframe(
                    pd.DataFrame(
                        [
                            {
                                "Month": r.month,
                                "Opening": r.opening_balance,
                                "Interest": r.interest,
                                "Prin (min)": r.principal_regular,
                                "Prin (extra)": r.principal_extra,
                                "Bonus": r.principal_lump,
                                "Closing": r.closing_balance,
                            }
                            for r in _f_base_sched.rows
                        ]
                    ),
                    use_container_width=True,
                    hide_index=True,
                )

        # What if I add extra?
        st.markdown("### What if I add extra?")
        st.caption(
            _md(
                "Optional what-ifs. Default: keep minimum until the second is gone. "
                "Student loans usually get the 3,500 / mo next (higher rate); use this section "
                "to compare pointing extra here from Jan 2028 instead. "
                "Toggle “start extra now” only if you want to try overlapping with the second."
            )
        )

        _f_plan = st.radio(
            "Pick a first-mortgage plan",
            [
                "A) Minimum only",
                "B) Add a monthly extra (after second)",
                "C) Monthly extra + one/two bonus lumps",
            ],
            index=0,
            key="debt_first_plan",
            horizontal=False,
            help="Baseline is minimum P&I. B/C: type any monthly extra in the box (starts blank).",
        )

        try:
            _f_def_y, _f_def_m = int(_f_extra_default_start[:4]), int(_f_extra_default_start[5:7])
            _f_def_start_date = date(_f_def_y, _f_def_m, 1)
        except Exception:
            _f_def_start_date = date(2028, 1, 1)

        _f_extra_from = _f_extra_default_start
        _f_extra_from_lbl = _f_extra_default_start
        _f_start_now = False
        if not _f_plan.startswith("A)"):
            _f_start_now = st.checkbox(
                "Start extra now (overlap with second) — off by default",
                value=False,
                key="debt_first_extra_now",
                help="When off, extra starts in the month below (default 2028-01).",
            )
            if _f_start_now:
                _f_extra_from = ""  # clear deferral — extra from projection start
                _f_extra_from_lbl = "now (from projection start)"
            else:
                _f_extra_start_in = st.date_input(
                    "Extra starts (month)",
                    value=_f_def_start_date,
                    key="debt_first_extra_start",
                    help="Default Jan 2028 — after second ~Dec 2027 payoff.",
                )
                _f_extra_from = f"{_f_extra_start_in.year}-{_f_extra_start_in.month:02d}"
                _f_extra_from_lbl = _f_extra_from

        _f_scenario_lumps: list = []
        _f_extra_amt = 0.0
        _f_scenario_label = "Minimum only"

        if _f_plan.startswith("A)"):
            _f_extra_amt = 0.0
            _f_scenario_label = "Minimum only"
        else:
            _f_extra_raw = st.text_input(
                "Monthly extra amount",
                value="",
                placeholder="Type any amount (e.g. 2000)",
                key="debt_first_extra_amt",
                help="Leave blank for 0. No default — enter whatever extra you want to model.",
            )
            try:
                _f_extra_amt = float(str(_f_extra_raw).replace(",", "").replace("$", "").strip() or 0)
            except ValueError:
                _f_extra_amt = 0.0
                st.caption("Enter a number for monthly extra (e.g. 2000).")
            if _f_extra_amt > 0:
                _f_scenario_label = f"{_f_extra_amt:,.0f} / mo extra from {_f_extra_from_lbl}"
            else:
                _f_scenario_label = f"No monthly extra yet (from {_f_extra_from_lbl})"
        if _f_plan.startswith("C)"):
            _f_c_preset = st.radio(
                "Bonuses on top of the monthly extra — quick pick",
                [
                    "One 24k example bonus",
                    "Jan 12k + Mar 12k (of start year)",
                    "Custom one or two",
                ],
                index=0,
                key="debt_first_bonus_preset",
                horizontal=False,
                help="Bonus months default relative to the extra-start year.",
            )
            _anchor_y = (
                int((_f_extra_from or "2028-01")[:4])
                if not _f_start_now
                else 2028
            )
            if _f_c_preset.startswith("One 24k"):
                _fc1_amt, _fc1_dt = 24000.0, date(_anchor_y, 1, 1)
                _fc2_amt, _fc2_dt = 0.0, date(_anchor_y, 3, 1)
                _show_two = False
            elif _f_c_preset.startswith("Jan 12k"):
                _fc1_amt, _fc1_dt = 12000.0, date(_anchor_y, 1, 1)
                _fc2_amt, _fc2_dt = 12000.0, date(_anchor_y, 3, 1)
                _show_two = True
            else:
                _fc1_amt, _fc1_dt = 24000.0, date(_anchor_y, 1, 1)
                _fc2_amt, _fc2_dt = 0.0, date(_anchor_y, 3, 1)
                _show_two = True

            st.markdown("**Bonus 1**")
            fc1a, fc1b = st.columns(2)
            with fc1a:
                _fc1_amt = st.number_input(
                    "Bonus 1 amount",
                    min_value=0.0,
                    value=float(_fc1_amt),
                    step=1000.0,
                    format="%.2f",
                    key=f"debt_first_b1_amt_{_f_c_preset}",
                    help="Example bonus — not a balance owed.",
                )
            with fc1b:
                _fc1_dt = st.date_input(
                    "Bonus 1 date",
                    value=_fc1_dt,
                    key=f"debt_first_b1_date_{_f_c_preset}",
                )
            if _show_two:
                st.markdown("**Bonus 2 (optional)**")
                fc2a, fc2b = st.columns(2)
                with fc2a:
                    _fc2_amt = st.number_input(
                        "Bonus 2 amount",
                        min_value=0.0,
                        value=float(_fc2_amt),
                        step=1000.0,
                        format="%.2f",
                        key=f"debt_first_b2_amt_{_f_c_preset}",
                    )
                with fc2b:
                    _fc2_dt = st.date_input(
                        "Bonus 2 date",
                        value=_fc2_dt,
                        key=f"debt_first_b2_date_{_f_c_preset}",
                    )
            _f_scenario_lumps = []
            if _fc1_amt > 0:
                _f_scenario_lumps.append({"amount": float(_fc1_amt), "date": _fc1_dt})
            if _show_two and _fc2_amt > 0:
                _f_scenario_lumps.append({"amount": float(_fc2_amt), "date": _fc2_dt})
            _bits = [
                f"{money(x['amount'])} ({parse_lump_date(x['date'])})"
                for x in _f_scenario_lumps
            ]
            if _f_extra_amt > 0:
                _f_scenario_label = f"{_f_extra_amt:,.0f} / mo from {_f_extra_from_lbl}"
            else:
                _f_scenario_label = f"No monthly extra yet (from {_f_extra_from_lbl})"
            if _bits:
                _f_scenario_label += " + " + " + ".join(_bits)

        # Build first-mortgage scenario
        if _f_extra_amt > 0 or _f_scenario_lumps:
            _f_sc_sched = schedule_for_debt(
                _first,
                extra_principal=_f_extra_amt,
                extra_start_month=_f_extra_from,
                lumps=_f_scenario_lumps or None,
            )
        else:
            _f_sc_sched = _f_base_sched
        _f_cmp = compare_schedules(_f_base_sched, _f_sc_sched)

        def _fmt_payoff_mo_f(ym):
            if not ym:
                return "—"
            try:
                y, m = int(ym[:4]), int(ym[5:7])
                return date(y, m, 1).strftime("%b %Y")
            except Exception:
                return ym

        _f_base_pay_h = _fmt_payoff_mo_f(_f_cmp.get("baseline_payoff_month"))
        _f_sc_pay_h = _fmt_payoff_mo_f(_f_cmp.get("scenario_payoff_month"))
        _f_months_saved = _f_cmp.get("months_saved")
        _f_int_saved = _f_cmp.get("interest_saved") or 0.0
        _f_has_scenario = bool(_f_extra_amt > 0 or _f_scenario_lumps)

        st.markdown("#### Side-by-side")
        if not _f_has_scenario:
            st.info(
                _md(
                    f"**Baseline:** paid off {_f_base_pay_h} on minimum P&I only. "
                    "Pick B or C to try redirecting 3,500 / mo after the second."
                )
            )
        else:
            if _f_months_saved and _f_months_saved > 0:
                _f_plain = (
                    f"Paid off {int(_f_months_saved)} months sooner · "
                    f"saves about {money(_f_int_saved)} in interest"
                )
            elif _f_months_saved == 0:
                _f_plain = f"Same payoff month · interest change {money(_f_int_saved)}"
            else:
                _f_plain = (
                    f"This plan payoff {_f_sc_pay_h} vs baseline {_f_base_pay_h} · "
                    f"interest change {money(_f_int_saved)}"
                )
            st.success(_md(_f_plain))

        fm1, fm2, fm3, fm4 = st.columns(4)
        fm1.metric("Baseline payoff", _f_base_pay_h)
        fm2.metric(
            "This plan payoff",
            _f_sc_pay_h if _f_has_scenario else _f_base_pay_h,
            delta=(
                f"−{int(_f_months_saved)} mo"
                if _f_has_scenario and _f_months_saved
                else None
            ),
            delta_color="normal",
        )
        fm3.metric(
            "Months faster",
            (
                f"{int(_f_months_saved)}"
                if _f_has_scenario and _f_months_saved is not None
                else "—"
            ),
        )
        fm4.metric(
            "Interest saved",
            money(_f_int_saved) if _f_has_scenario else "—",
            help=_md(
                f"Baseline interest {money(_f_cmp.get('baseline_total_interest'))} → "
                f"this plan {money(_f_cmp.get('scenario_total_interest'))}"
            ),
        )
        if _f_has_scenario:
            st.caption(_md(f"Comparing: **{_f_scenario_label}** vs baseline (minimum only)."))

        if _f_has_scenario and _f_series:
            _f_sc_series = balance_series(_f_sc_sched)
            _f_cmp_df = pd.DataFrame(
                {
                    "Baseline (min only)": {r["month"]: r["balance"] for r in _f_series},
                    "This plan": {r["month"]: r["balance"] for r in _f_sc_series},
                }
            ).sort_index()
            _f_all_months = sorted(set(_f_cmp_df.index))
            _f_cmp_df = _f_cmp_df.reindex(_f_all_months).fillna(0.0)
            st.markdown("##### Baseline vs this plan")
            try:
                import altair as alt

                _f_melt = _f_cmp_df.reset_index().rename(columns={"index": "month"})
                _f_long = _f_melt.melt("month", var_name="Plan", value_name="balance")
                _f_overlay = (
                    alt.Chart(_f_long)
                    .mark_line(strokeWidth=2.5)
                    .encode(
                        x=alt.X("month:N", title="Month", sort=None),
                        y=alt.Y("balance:Q", title="Balance", axis=alt.Axis(format="$,.0f")),
                        color=alt.Color(
                            "Plan:N",
                            scale=alt.Scale(
                                domain=["Baseline (min only)", "This plan"],
                                range=["#2a6f97", "#c45c26"],
                            ),
                        ),
                        tooltip=[
                            "month",
                            "Plan",
                            alt.Tooltip("balance:Q", format="$,.2f"),
                        ],
                    )
                    .properties(height=280)
                )
                st.altair_chart(_f_overlay, use_container_width=True)
            except Exception:
                st.line_chart(_f_cmp_df, height=280)

            with st.expander("Month-by-month payoff detail (first · this plan)", expanded=False):
                st.dataframe(
                    pd.DataFrame(
                        [
                            {
                                "Month": r.month,
                                "Opening": r.opening_balance,
                                "Interest": r.interest,
                                "Prin (min)": r.principal_regular,
                                "Prin (extra)": r.principal_extra,
                                "Bonus": r.principal_lump,
                                "Closing": r.closing_balance,
                            }
                            for r in _f_sc_sched.rows
                        ]
                    ),
                    use_container_width=True,
                    hide_index=True,
                )

        with st.expander("Refresh first-mortgage balance (screenshots)", expanded=False):
            st.caption("Saved to the debts file — does not touch checking start balance or the second.")
            with st.form("debt_first_refresh"):
                fnb = st.number_input(
                    "Current balance",
                    value=float(_first["current_balance"]),
                    step=100.0,
                    format="%.2f",
                    key="debt_first_bal_refresh",
                )
                fnas = st.text_input(
                    "As of",
                    value=_first.get("balance_as_of") or "",
                    key="debt_first_asof_refresh",
                )
                fnpi = st.number_input(
                    "P&I regular payment",
                    value=float(_first.get("regular_payment") or 0),
                    step=10.0,
                    format="%.2f",
                    key="debt_first_pi_refresh",
                )
                fnesc = st.number_input(
                    "Monthly escrow (info)",
                    value=float(_first.get("escrow") or 0),
                    step=10.0,
                    format="%.2f",
                    key="debt_first_escrow_refresh",
                )
                if st.form_submit_button("Save first-mortgage snapshot"):
                    store = load_debts()
                    d = get_debt(store, "mortgage_first")
                    if d is not None:
                        d["current_balance"] = float(fnb)
                        d["status"] = "active"
                        if fnas.strip():
                            d["balance_as_of"] = fnas.strip()
                        d["regular_payment"] = float(fnpi)
                        d["escrow"] = float(fnesc)
                        d["total_payment"] = round(float(fnpi) + float(fnesc), 2)
                        save_debts(store)
                        st.success("Saved to data/debts.json")
                        st.rerun()

    # ----- Refresh second-mortgage balance -----
    with st.expander("Refresh second-mortgage balance (screenshots / CSV)", expanded=False):
        st.caption(
            "Saved to the debts file — does not touch checking start balance."
        )
        with st.form("debt_second_refresh"):
            nb = st.number_input(
                "Current balance",
                value=float(_second["current_balance"]),
                step=100.0,
                format="%.2f",
                key="debt_sec_bal",
            )
            nas = st.text_input(
                "As of",
                value=_second.get("balance_as_of") or "",
                key="debt_sec_asof",
            )
            nextra = st.number_input(
                "Extra principal / month",
                value=float(_second.get("extra_principal_monthly") or 3500),
                step=100.0,
                format="%.2f",
                key="debt_sec_extra",
            )
            if st.form_submit_button("Save second-mortgage snapshot"):
                update_debt_balance(
                    "mortgage_second",
                    current_balance=float(nb),
                    balance_as_of=nas.strip() or None,
                    extra_principal_monthly=float(nextra),
                )
                st.success("Saved to data/debts.json")
                st.rerun()

    st.caption(_md(_debt_store.get("cashflow_link_note") or ""))

# ---------- RETIREMENT RUNWAY ----------
elif page == "Retirement runway":
    st.title("Retirement runway")
    st.caption(_md("Age-aware Comfort targets at 50 / 55 / 60 · BrokerageLink stays on this page only."))

    _ret_plan = load_retirement_plan()
    _ret_acc = load_retirement_accounts()
    _ret_assets = current_retirement_assets(_ret_acc)
    _ret_snap = load_retirement_snapshot()
    _person = _ret_plan.get("person") or {}
    _assumptions = dict(_ret_plan.get("assumptions") or {})
    _age_now = float(
        (_ret_snap or {}).get("age")
        or _person.get("age_years")
        or 40
    )
    _real_ret = float(_assumptions.get("real_return") or 0.05)
    _hc_default = float(
        (_ret_snap or {}).get("healthcare_temp_adder_annual")
        or _assumptions.get("healthcare_temp_adder_annual")
        or HEALTHCARE_TEMP_ADDER_ANNUAL
    )

    # Lifestyle levels from snapshot temps (Comfort default until warehouse learns)
    _snap_spend = (_ret_snap or {}).get("spend") or {}
    _ln = _ret_plan.get("lifestyle_need") or {}
    _comfort_default = float(
        _snap_spend.get("comfort_annual")
        or _ln.get("comfort_annual")
        or DEFAULT_COMFORT_ANNUAL
    )
    _floor_default = float(
        _snap_spend.get("floor_annual")
        or _ln.get("floor_annual")
        or (_comfort_default * 0.80)
    )
    _life_default = float(
        _snap_spend.get("life_annual")
        or _ln.get("life_annual")
        or (_comfort_default * 1.20)
    )
    _stated_monthly = float(
        _snap_spend.get("stated_monthly")
        or _ln.get("stated_monthly")
        or DEFAULT_STATED_MONTHLY
    )

    _wh = warehouse_status()
    if not _wh["learning_live"]:
        st.warning(_md(f"**Warehouse:** {_wh['banner']}"))
    else:
        st.success(_md(f"**Warehouse:** {_wh['banner']}"))

    # --- Lifestyle: Floor·Comfort·Life (formatted heroes; edit in expander) ---
    st.markdown("### Lifestyle")
    _obs = _snap_spend.get("t12_median")
    _obs_val = float(_obs) if _obs not in (None, "") else None

    with st.expander("Edit Floor / Comfort / Life ($/yr)", expanded=False):
        _lv1, _lv2, _lv3 = st.columns(3)
        with _lv1:
            _floor_annual = st.number_input(
                "Floor (rigid) $/yr",
                min_value=0.0,
                value=float(round(_floor_default, 2)),
                step=500.0,
                format="%.2f",
                key="ret_floor_annual",
                help="Bare-bones lifestyle — 80% of Comfort by default.",
            )
        with _lv2:
            _comfort_annual = st.number_input(
                "Comfort (default) $/yr",
                min_value=0.0,
                value=float(round(_comfort_default, 2)),
                step=500.0,
                format="%.2f",
                key="ret_comfort_annual",
                help="Primary planning need.",
            )
        with _lv3:
            _life_annual = st.number_input(
                "Life (aspirational) $/yr",
                min_value=0.0,
                value=float(round(_life_default, 2)),
                step=500.0,
                format="%.2f",
                key="ret_life_annual",
                help="Richer lifestyle — 120% of Comfort by default.",
            )

    _levels = lifestyle_levels(
        _comfort_annual, floor_annual=_floor_annual, life_annual=_life_annual
    )

    _chip = st.radio(
        "Planning level",
        options=["Floor", "Comfort", "Life"],
        index=1,
        horizontal=True,
        key="ret_lifestyle_chip",
        label_visibility="collapsed",
    )
    st.caption(
        _md(
            "**Floor** — bare-bones living (~80% of Comfort).\n"
            "**Comfort** — the lifestyle you plan around (default).\n"
            "**Life** — richer living (~120% of Comfort)."
        )
    )
    _hero_annual = {
        "Floor": _levels["floor_annual"],
        "Comfort": _levels["comfort_annual"],
        "Life": _levels["life_annual"],
    }[_chip]
    _hero_monthly = _hero_annual / 12.0
    st.markdown(
        f"""
<div style="border-radius:14px;padding:0.9rem 1rem;margin:0.25rem 0 0.55rem;
background:linear-gradient(135deg,#eef2fb 0%,#f7f9fc 100%);border:1px solid #c5d0e8;">
  <div style="font-size:0.8rem;font-weight:700;color:#5b6475;letter-spacing:0.04em;">{_chip.upper()} · $/YR</div>
  <div style="font-size:1.85rem;font-weight:800;color:#1e293b;margin-top:0.15rem;">{ret_format_money(_hero_annual)}</div>
  <div style="color:#3a4254;margin-top:0.2rem;">{_chip} is about {ret_format_money(_hero_monthly)}/mo.</div>
  <div style="margin-top:0.55rem;font-size:0.88rem;color:#4b5563;">
    <span style="display:inline-block;padding:0.2rem 0.55rem;margin-right:0.35rem;border-radius:999px;background:#fff;border:1px solid #d1d5db;">Floor {ret_format_money(_levels['floor_annual'])}/yr</span>
    <span style="display:inline-block;padding:0.2rem 0.55rem;margin-right:0.35rem;border-radius:999px;background:#fff;border:1px solid #d1d5db;">Comfort {ret_format_money(_levels['comfort_annual'])}/yr</span>
    <span style="display:inline-block;padding:0.2rem 0.55rem;border-radius:999px;background:#fff;border:1px solid #d1d5db;">Life {ret_format_money(_levels['life_annual'])}/yr</span>
  </div>
</div>
        """,
        unsafe_allow_html=True,
    )
    st.caption(
        _md(
            f"Monthly: Floor {ret_format_money(_levels['floor_monthly'])}/mo · "
            f"Comfort {ret_format_money(_levels['comfort_monthly'])}/mo · "
            f"Life {ret_format_money(_levels['life_monthly'])}/mo"
        )
    )

    _ls1, _ls2, _ls3 = st.columns(3)
    with _ls1:
        st.metric("Stated", ret_format_money(_stated_monthly) + "/mo")
    with _ls2:
        st.metric(
            "Observed",
            (ret_format_money(_obs_val) + "/mo") if _obs_val is not None else "n/a",
            help="T12 median from transactions warehouse",
        )
    with _ls3:
        st.metric(
            "Suggested",
            ret_format_money(_levels["comfort_monthly"]) + "/mo",
            help="Comfort ÷ 12 (live)",
        )

    _hc_on = st.toggle(
        "Healthcare adder (temp $24k/yr couple pre-65)",
        value=False,
        key="ret_hc_toggle",
        help="Shows Comfort nest egg with/without a temporary $24,000/yr healthcare adder before Medicare.",
    )
    _hc_adder = _hc_default if _hc_on else 0.0
    if _hc_on:
        st.caption(
            _md(
                f"Healthcare adder **{money(_hc_default)}/yr** → "
                f"Comfort+HC {money(_comfort_annual + _hc_default)}/yr"
            )
        )

    # --- Three one-line bullets (not a blue info dump) ---
    st.markdown(
        _md(
            f"- **{ret_format_pct(_real_ret)}** real return assumed\n"
            "- Social Security **$0** until the claim age\n"
            "- **SPCX** is not SpaceX stock"
        )
    )
    with st.expander("Plain English: what do these words mean?"):
        st.markdown(
            _md(
                "**Floor / Comfort / Life** — how much yearly spending you want in retirement. "
                "Floor is bare-bones, Comfort is the plan you aim for, Life is richer.\n\n"
                "**Safe spend %** (sometimes called SWR) — how much of the nest egg you can "
                "safely take out each year without running dry. Retiring earlier uses a "
                f"lower %: age 50 → {ret_format_pct(AGE_AWARE_SWR[50])} "
                f"(about {AGE_AWARE_MULTIPLIER[50]:.1f}× Comfort), "
                f"55 → {ret_format_pct(AGE_AWARE_SWR[55])} "
                f"(about {AGE_AWARE_MULTIPLIER[55]:.1f}×), "
                f"60 → {ret_format_pct(AGE_AWARE_SWR[60])} "
                f"(about {AGE_AWARE_MULTIPLIER[60]:.1f}×).\n\n"
                "**Comfort target** — nest egg needed so Comfort spending lasts at that age's "
                "safe spend %. **Projected** — where today's investments grow if returns hold. "
                "**Gap / Extra save/mo** — how short you are, and roughly how much extra to save "
                "each month to close it.\n\n"
                f"**Healthcare toggle** — temporary {money(HEALTHCARE_TEMP_ADDER_ANNUAL)}/yr "
                "couple cushion before Medicare (age 65).\n\n"
                "**SPCX** — BrokerageLink is ~100% AXS SPAC and New Issue ETF, not SpaceX stock. "
                "Concentrated, so returns can swing more than a diversified mix.\n\n"
                "**Flex comfort** (secondary) — a slightly leaner nest-egg check using a "
                "higher spend rate. **Classic 25×** — old rule of thumb (Comfort × 25); "
                "shown only as a footnote, not the main target."
            )
        )

    _tiles = evaluate_lifestyle_tiles(
        ages=RETIREMENT_DEFAULT_AGES,
        current_age=_age_now,
        floor_annual=_floor_annual,
        comfort_annual=_comfort_annual,
        life_annual=_life_annual,
        current_assets=float(_ret_assets["total"]),
        real_return=float(_real_ret),
        healthcare_adder_annual=_hc_adder,
    )

    # --- Age tiles ---
    st.markdown("### Runway by retirement age")
    st.caption(
        _md(
            f"Age **{int(_age_now)}** · assets **{money(_ret_assets['total'])}** "
            f"as of {_ret_assets.get('as_of') or '—'}. "
            "Each card answers: *if you stop working at this age, how big a nest egg "
            "do you need for Comfort living, and are you on track?*"
        )
    )

    def _ret_dollar_html(s: str) -> str:
        return str(s).replace("$", "&#36;")

    st.markdown(
        """
<style>
.ret-age-row {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 0.85rem;
  margin: 0.4rem 0 1rem 0;
}
@media (max-width: 900px) {
  .ret-age-row { grid-template-columns: 1fr; }
}
.ret-age-card {
  border-radius: 16px;
  padding: 1rem 1.05rem 0.9rem;
  background: linear-gradient(160deg, #f7f9fc 0%, #eef3f8 100%);
  border: 1px solid #d7dee8;
  box-shadow: 0 1px 2px rgba(40, 55, 80, 0.04);
  display: flex;
  flex-direction: column;
  gap: 0.28rem;
  min-height: 11.5rem;
}
.ret-age-card.ret-ontrack {
  background: linear-gradient(160deg, #e8f8ef 0%, #f4fcf7 100%);
  border-color: #9ad4b0;
}
.ret-age-card.ret-short {
  background: linear-gradient(160deg, #f7f4ef 0%, #fbf8f3 100%);
  border-color: #e2d5c3;
}
.ret-age-head {
  font-size: 0.78rem; font-weight: 650; letter-spacing: 0.03em;
  text-transform: uppercase; color: #5b6575;
}
.ret-age-hero {
  font-size: 1.55rem; font-weight: 750; color: #1f2937;
  letter-spacing: -0.02em; line-height: 1.15;
}
.ret-age-hero-label {
  font-size: 0.72rem; font-weight: 600; color: #6b7280; margin-top: 0.15rem;
}
.ret-age-proj {
  font-size: 1.02rem; font-weight: 650; color: #334155; margin-top: 0.15rem;
}
.ret-age-quiet {
  font-size: 0.78rem; color: #6b7280; margin-top: 0.1rem;
}
.ret-age-chips {
  display: flex; flex-wrap: wrap; gap: 0.35rem; margin-top: 0.35rem;
}
.ret-chip {
  font-size: 0.72rem; font-weight: 600; color: #475569;
  background: rgba(255,255,255,0.72); border: 1px solid #d7dee8;
  border-radius: 999px; padding: 0.18rem 0.55rem;
}
.ret-gap-pos { color: #1b6b3a; font-weight: 650; }
.ret-gap-neg { color: #7a4a1e; font-weight: 650; }
</style>
        """,
        unsafe_allow_html=True,
    )

    _tile_htmls = []
    for _t in _tiles:
        _comfort_show = _t.comfort_with_healthcare if _hc_on else _t.comfort
        _gap_show = _t.gap_comfort_with_healthcare if _hc_on else _t.gap_comfort
        _extra_show = _t.extra_mo_with_healthcare if _hc_on else _t.extra_mo
        _kind = "ret-ontrack" if _gap_show <= 0 else "ret-short"
        if _gap_show <= 0:
            _gap_line = '<span class="ret-gap-pos">On track</span>'
        else:
            _gap_line = (
                f'<span class="ret-gap-neg">Gap {_ret_dollar_html(money(_gap_show))}</span>'
                f" · extra {_ret_dollar_html(money(_extra_show))}/mo"
            )
        _tile_htmls.append(
            f'<div class="ret-age-card {_kind}">'
            f'<div class="ret-age-head">Age {_t.retire_age} · '
            f'{_ret_dollar_html(ret_format_years(_t.years_to_go))}</div>'
            f'<div class="ret-age-hero-label">Comfort target</div>'
            f'<div class="ret-age-hero">'
            f'{_ret_dollar_html(ret_format_money_compact(_comfort_show))}</div>'
            f'<div class="ret-age-proj">Projected '
            f'{_ret_dollar_html(money(_t.projected_base))}</div>'
            f'<div class="ret-age-quiet">{_gap_line}</div>'
            f'<div class="ret-age-chips">'
            f'<span class="ret-chip">Floor {_ret_dollar_html(ret_format_money_compact(_t.floor))}</span>'
            f'<span class="ret-chip">Life {_ret_dollar_html(ret_format_money_compact(_t.life))}</span>'
            f'<span class="ret-chip">Safe spend {_ret_dollar_html(ret_format_pct(_t.swr_rigid))}</span>'
            f"</div></div>"
        )
    st.markdown(
        '<div class="ret-age-row">' + "".join(_tile_htmls) + "</div>",
        unsafe_allow_html=True,
    )

    # --- Detail table (primary cols; secondary in expander) ---
    st.markdown("#### Compare ages side by side")
    st.caption(
        _md(
            "Same story as the cards, in a grid. "
            "**Safe spend %** = share of the nest egg you can take each year. "
            "**Comfort target** = nest egg needed. **Projected** = where you land if "
            "investments keep growing. **Gap** = shortfall. **Extra save/mo** ≈ monthly "
            "savings to close that gap before that age."
        )
    )
    _primary_rows = []
    _extra_rows = []
    for t in _tiles:
        _c = t.comfort_with_healthcare if _hc_on else t.comfort
        _g = max(0.0, t.gap_comfort_with_healthcare if _hc_on else t.gap_comfort)
        _e = t.extra_mo_with_healthcare if _hc_on else t.extra_mo
        _primary_rows.append(
            {
                "Retire age": t.retire_age,
                "Years to go": ret_format_years(t.years_to_go),
                "Safe spend %": ret_format_pct(t.swr_rigid),
                "Comfort target": money(_c),
                "Projected": money(t.projected_base),
                "Gap to Comfort": money(_g),
                "Extra save/mo": money(_e),
            }
        )
        _extra_rows.append(
            {
                "Retire age": t.retire_age,
                "Floor nest egg": money(t.floor),
                "Life nest egg": money(t.life),
                "Flex Comfort nest egg": money(t.flex_comfort),
            }
        )
    _tdf_show = pd.DataFrame(_primary_rows)
    _money_cols = ["Comfort target", "Projected", "Gap to Comfort", "Extra save/mo"]
    _col_cfg = {
        c: st.column_config.Column(c, alignment="right")
        for c in _money_cols
    }
    _col_cfg["Years to go"] = st.column_config.Column("Years to go", alignment="right")
    _col_cfg["Safe spend %"] = st.column_config.Column(
        "Safe spend %",
        help="Safe Withdrawal Rate (SWR): % of nest egg you can spend each year.",
        alignment="right",
    )
    st.dataframe(
        _tdf_show,
        use_container_width=True,
        hide_index=True,
        column_config=_col_cfg,
    )
    with st.expander("Also see Floor, Life, and Flex Comfort nest eggs"):
        st.caption(
            _md(
                "**Floor nest egg** — savings needed for bare-bones living. "
                "**Life nest egg** — for the richer lifestyle. "
                "**Flex Comfort** — a slightly leaner Comfort check (secondary, not the main plan)."
            )
        )
        _xdf = pd.DataFrame(_extra_rows)
        _xcfg = {
            c: st.column_config.Column(c, alignment="right")
            for c in ("Floor nest egg", "Life nest egg", "Flex Comfort nest egg")
        }
        st.dataframe(_xdf, use_container_width=True, hide_index=True, column_config=_xcfg)

    _classic = classic_25x(_comfort_annual)
    st.caption(
        _md(
            f"Old rule of thumb (Comfort × 25) would say **{money(_classic)}** — "
            f"shown for comparison only. This page uses the age-based safe spend % instead."
        )
    )

    if _hc_on:
        st.markdown("#### Comfort nest egg — with vs without healthcare")
        st.caption(
            _md(
                "HC = healthcare cushion before Medicare. "
                "Compares Comfort nest egg and monthly catch-up with and without that temporary adder."
            )
        )
        _hc_rows = []
        for t in _tiles:
            _hc_rows.append(
                {
                    "Retire age": t.retire_age,
                    "Comfort (no healthcare)": money(t.comfort),
                    "Comfort + healthcare": money(t.comfort_with_healthcare),
                    "Extra save/mo (no HC)": money(t.extra_mo),
                    "Extra save/mo (+HC)": money(t.extra_mo_with_healthcare),
                }
            )
        _hcdf = pd.DataFrame(_hc_rows)
        _hccfg = {
            c: st.column_config.Column(c, alignment="right")
            for c in (
                "Comfort (no healthcare)",
                "Comfort + healthcare",
                "Extra save/mo (no HC)",
                "Extra save/mo (+HC)",
            )
        }
        st.dataframe(_hcdf, use_container_width=True, hide_index=True, column_config=_hccfg)

    # Chart: Needed (= age Comfort target) vs Projected — never classic 25× thrice
    try:
        _chart_rows = []
        for t in _tiles:
            _c_val = t.comfort_with_healthcare if _hc_on else t.comfort
            _chart_rows.append(
                {"Age": str(t.retire_age), "Series": "Needed", "Amount": float(_c_val)}
            )
            _chart_rows.append(
                {
                    "Age": str(t.retire_age),
                    "Series": "Projected",
                    "Amount": float(t.projected_base),
                }
            )
        labeled_bars(
            pd.DataFrame(_chart_rows),
            x_col="Age",
            y_col="Amount",
            color_col="Series",
            height=280,
            title="Needed (Comfort) vs Projected",
            color_domain=["Needed", "Projected"],
            color_range=["#c45c26", "#2f6fed"],
        )
    except Exception:
        _fallback = pd.DataFrame(
            {
                "Needed": [
                    (t.comfort_with_healthcare if _hc_on else t.comfort) for t in _tiles
                ],
                "Projected": [t.projected_base for t in _tiles],
            },
            index=[t.retire_age for t in _tiles],
        )
        st.bar_chart(_fallback)

    # --- Asset snapshot ---
    st.markdown("### Asset snapshot")
    _as1, _as2, _as3 = st.columns(3)
    with _as1:
        st.metric("BrokerageLink", money(_ret_assets["brokeragelink"]))
        st.caption("Retirement math only — off Dashboard Brokerage")
    with _as2:
        st.metric("Fidelity Individual", money(_ret_assets["individual"]))
        st.caption(_md("Taxable brokerage · Z21443850"))
    with _as3:
        st.metric("Total", money(_ret_assets["total"]))
        _bridge = taxable_bridge_months(
            float(_ret_assets["individual"]), _comfort_annual
        )
        st.caption(
            _md(
                f"Taxable bridge: ~{float(_bridge):.1f} months of Comfort "
                f"· as of {_ret_assets.get('as_of') or '—'}"
            )
        )

    _bl = (_ret_acc.get("brokeragelink") or {})
    _pos = _bl.get("positions") or []
    if _pos:
        with st.expander("BrokerageLink positions"):
            for _p in _pos:
                st.write(
                    f"- **{_p.get('ticker')}** — {_p.get('name')}: "
                    f"{money(float(_p.get('value') or 0))}"
                )

    _buckets = _ret_plan.get("allocation_buckets") or []
    if _buckets:
        _alloc_df = pd.DataFrame(
            [
                {
                    "Bucket": b.get("label") or b.get("id"),
                    "Pct": float(b.get("pct") or 0),
                }
                for b in _buckets
            ]
        )
        with st.expander("Coarse allocation"):
            st.caption(
                _md(
                    _ret_plan.get("allocation_source")
                    or _ret_plan.get("allocation_placeholder")
                    or "Holdings snapshot — update anytime with a new screenshot."
                )
            )
            try:
                labeled_bars(
                    _alloc_df,
                    x_col="Bucket",
                    y_col="Pct",
                    height=220,
                    title="Coarse allocation (editable in JSON)",
                    money_format=False,
                )
            except Exception:
                st.dataframe(_alloc_df, hide_index=True, use_container_width=True)

    with st.expander("Course suggestions"):
        for _tip in retirement_course_suggestions(_ret_plan):
            st.markdown(f"- {_md(_tip)}")

    st.divider()
    if st.button("Save retirement snapshot", key="ret_save"):
        _ret_plan["assumptions"]["real_return"] = float(_real_ret)
        _ret_plan["assumptions"]["healthcare_temp_adder_annual"] = float(_hc_default)
        _ret_plan["lifestyle_need"] = dict(_ret_plan.get("lifestyle_need") or {})
        _ret_plan["lifestyle_need"]["comfort_annual"] = float(_comfort_annual)
        _ret_plan["lifestyle_need"]["floor_annual"] = float(_floor_annual)
        _ret_plan["lifestyle_need"]["life_annual"] = float(_life_annual)
        _ret_plan["lifestyle_need"]["stated_monthly"] = float(_stated_monthly)
        _ret_plan["lifestyle_need"]["source"] = (
            "temporary_twin" if not _wh["learning_live"] else "twin_avg_expenses"
        )
        _ret_plan["as_of"] = date.today().isoformat()
        save_retirement_plan(_ret_plan)
        _new_snap = build_retirement_snapshot(
            current_age=_age_now,
            comfort_annual=_comfort_annual,
            floor_annual=_floor_annual,
            life_annual=_life_annual,
            stated_monthly=_stated_monthly,
            current_assets=float(_ret_assets["total"]),
            individual=float(_ret_assets["individual"]),
            brokeragelink=float(_ret_assets["brokeragelink"]),
            real_return=float(_real_ret),
            healthcare_adder_annual=float(_hc_default),
            as_of=date.today().isoformat(),
            accounts=_ret_acc,
        )
        save_retirement_snapshot(_new_snap)
        append_retirement_history(_new_snap)
        st.success("Saved data/retirement_snapshot.json + retirement_plan.json")
        st.rerun()

    if _ret_snap:
        _snap_classic = _ret_snap.get("classic_25x_comfort")
        _snap_bridge = _ret_snap.get("taxable_bridge_months")
        _classic_txt = (
            money(float(_snap_classic))
            if _snap_classic not in (None, "")
            else "—"
        )
        _bridge_txt = (
            ret_format_months(float(_snap_bridge))
            if _snap_bridge not in (None, "")
            else "—"
        )
        st.caption(
            _md(
                f"Snapshot **{_ret_snap.get('as_of')}** · "
                f"path@55 Comfort: **{_ret_snap.get('path_status_55_comfort')}** · "
                f"classic 25× {_classic_txt} · bridge {_bridge_txt}"
            )
        )

    st.caption(
        _md(
            "Planning math, not licensed advice. "
            "Primary mortgage · taxable bridge before 50 · capture freed cash · "
            "rebuild Comfort from transactions when the warehouse fills."
        )
    )

    # --- Tax layer (does not replace Retirement OS / Floor·Comfort·Life) ---
    st.divider()
    st.markdown("### Tax layer")
    st.caption(
        _md(
            "MFJ 2026 planning estimate · Florida state income tax **$0**. "
            "Does not change Floor / Comfort / Life runway math. "
            "BrokerageLink stays pre-tax until you actually convert."
        )
    )

    try:
        _tax_bundle = tax_layer_bundle()
        _tax_base = _tax_bundle["base"]
        _tax_scen = _tax_bundle["scenarios"]
        _tax_paths = _tax_bundle["paths"]
        _tax_verdict = _tax_bundle["verdict"]
        _tax_margin = _tax_base.get("marginal") or {}
        _tax_room = _tax_margin.get("room_to_next")
        _tax_room_txt = (
            ret_format_money(float(_tax_room))
            if _tax_room is not None
            else "top bracket"
        )
        _tax_eff = float(_tax_base.get("effective_rate_on_taxable") or 0.0)

        st.markdown(
            f"""
<div style="border-radius:16px;padding:1.05rem 1.15rem 0.95rem;
  background:linear-gradient(160deg,#f7f9fc 0%,#eef3f8 100%);
  border:1px solid #d7dee8;box-shadow:0 1px 2px rgba(40,55,80,0.04);
  margin:0.35rem 0 1rem 0;">
  <div style="font-size:0.78rem;font-weight:650;letter-spacing:0.03em;
    text-transform:uppercase;color:#5b6575;">2026 MFJ snapshot</div>
  <div style="font-size:1.55rem;font-weight:750;color:#1f2937;
    letter-spacing:-0.02em;line-height:1.15;margin-top:0.2rem;">
    {_ret_dollar_html(_tax_margin.get('label') or '—')} marginal
    · {_ret_dollar_html(_tax_room_txt)} room
  </div>
  <div style="color:#3a4254;margin-top:0.35rem;font-size:0.9rem;">
    Extra Roth dollars first cost about
    {_ret_dollar_html(ret_format_pct(float(_tax_margin.get('rate') or 0)))}
    federal (FL state {_ret_dollar_html('$0')}).
  </div>
  <div style="margin-top:0.55rem;">
    <span style="display:inline-block;padding:0.2rem 0.55rem;margin:0.15rem 0.35rem 0.15rem 0;
      border-radius:999px;background:#fff;border:1px solid #d1d5db;font-size:0.78rem;font-weight:600;color:#475569;">
      AGI proxy {_ret_dollar_html(ret_format_money(float(_tax_base['agi_proxy'])))}
    </span>
    <span style="display:inline-block;padding:0.2rem 0.55rem;margin:0.15rem 0.35rem 0.15rem 0;
      border-radius:999px;background:#fff;border:1px solid #d1d5db;font-size:0.78rem;font-weight:600;color:#475569;">
      Taxable {_ret_dollar_html(ret_format_money(float(_tax_base['taxable_proxy'])))}
    </span>
    <span style="display:inline-block;padding:0.2rem 0.55rem;margin:0.15rem 0;
      border-radius:999px;background:#fff;border:1px solid #d1d5db;font-size:0.78rem;font-weight:600;color:#475569;">
      Effective {_ret_dollar_html(ret_format_pct(_tax_eff))}
    </span>
  </div>
  <div style="font-size:0.75rem;color:#6b7280;margin-top:0.55rem;">
    Florida · state income tax {_ret_dollar_html('$0')} · estimate only (no CTC / SE tax in this layer).
  </div>
</div>
            """,
            unsafe_allow_html=True,
        )

        st.markdown("#### Paths")
        st.caption(_md("Three choices — tap a card, then read the simple table below."))

        if "ret_tax_path_id" not in st.session_state:
            st.session_state.ret_tax_path_id = "A"

        _paths_ui = list(_tax_paths) if _tax_paths else [
            {
                "id": "A",
                "title": "Path A — Leave as-is",
                "subtitle": "No Roth move this year",
                "blurb": (
                    "Leave BrokerageLink pre-tax this year — finish the second mortgage "
                    "before paying tax to convert."
                ),
            },
            {
                "id": "B",
                "title": "Path B — Move some to Roth",
                "subtitle": "See the extra tax this year",
                "blurb": (
                    "Optionally move some pre-tax 401k (workplace retirement) into Roth "
                    "and see the extra federal tax this year."
                ),
            },
            {
                "id": "C",
                "title": "Path C — Mega backdoor",
                "subtitle": "Mega backdoor: AVAILABLE",
                "blurb": (
                    "Grow future paycheck dollars as Roth. Not the same as converting "
                    "today’s BrokerageLink balance."
                ),
            },
        ]
        # Ensure three lanes with stable A/B/C ids
        while len(_paths_ui) < 3:
            _paths_ui.append({"id": ("A", "B", "C")[len(_paths_ui)], "title": f"Path {('A','B','C')[len(_paths_ui)]}", "subtitle": "", "blurb": ""})

        _path_cols = st.columns(3)
        for _i, _p in enumerate(_paths_ui[:3]):
            _pid = str(_p.get("id") or _p.get("key") or ("A", "B", "C")[_i])
            _selected = str(st.session_state.ret_tax_path_id).upper() == _pid.upper()
            if _selected:
                _border = "2px solid #22c55e"
                _bg = "linear-gradient(160deg, #e8f8ef 0%, #f4fcf7 100%)"
            else:
                _border = "1px solid #d7dee8"
                _bg = "linear-gradient(160deg, #f7f9fc 0%, #eef3f8 100%)"
            _title_h = _ret_dollar_html(str(_p.get("title") or f"Path {_pid}"))
            _sub_h = _ret_dollar_html(str(_p.get("subtitle") or ""))
            _blurb_h = _ret_dollar_html(str(_p.get("blurb") or ""))
            with _path_cols[_i]:
                st.markdown(
                    f"""
<div style="border-radius:16px;padding:1rem 1.05rem 0.9rem;min-height:11.5rem;
  background:{_bg};border:{_border};
  box-shadow:0 1px 2px rgba(40,55,80,0.04);
  display:flex;flex-direction:column;gap:0.28rem;">
  <div style="font-size:0.95rem;font-weight:750;color:#1f2937;letter-spacing:-0.01em;">
    {_title_h}
  </div>
  <div style="font-size:0.72rem;font-weight:600;color:#6b7280;margin-top:0.1rem;">
    {_sub_h}
  </div>
  <div style="font-size:0.78rem;color:#6b7280;margin-top:0.25rem;line-height:1.35;">
    {_blurb_h}
  </div>
</div>
                    """,
                    unsafe_allow_html=True,
                )
                if st.button(
                    f"Select {_pid}" if not _selected else f"Selected · {_pid}",
                    key=f"ret_tax_path_btn_{_pid}",
                    use_container_width=True,
                    type="primary" if _selected else "secondary",
                ):
                    st.session_state.ret_tax_path_id = _pid
                    st.rerun()

        _sel_id = str(st.session_state.get("ret_tax_path_id") or "A")
        _sel_path = None
        for _p in _paths_ui:
            _pid = str(_p.get("id") or _p.get("key") or _p.get("title") or "")
            if _pid.upper() == _sel_id.upper():
                _sel_path = _p
                break
        if _sel_path is None and _paths_ui:
            _sel_path = _paths_ui[0]
            _sel_id = str(_sel_path.get("id") or "A")

        _sel_upper = (
            f"{_sel_path.get('title') or ''} {_sel_path.get('subtitle') or ''} {_sel_id}"
        ).upper()
        _is_a = (
            "STAY PRE-TAX" in _sel_upper
            or "LEAVE AS-IS" in _sel_upper
            or _sel_upper.startswith("PATH A")
            or _sel_id in ("A", "a", "stay")
        )
        _is_b = (
            "CONVERSION" in _sel_upper
            or "CONTROLLED" in _sel_upper
            or "MOVE SOME TO ROTH" in _sel_upper
            or _sel_upper.startswith("PATH B")
            or _sel_id in ("B", "b", "convert")
        )
        _is_c = (
            "MEGA" in _sel_upper
            or "BACKDOOR" in _sel_upper
            or _sel_upper.startswith("PATH C")
            or _sel_id in ("C", "c", "mega")
        )
        # Fallback by id letter if titles differ
        if not (_is_a or _is_b or _is_c):
            _u = _sel_id.upper()
            _is_a, _is_b, _is_c = (_u == "A", _u == "B", _u == "C")

        if _is_a:
            _bl_bal_a = float(_tax_base.get("brokeragelink_balance") or 515916.24)
            _bracket_lbl = _tax_margin.get("label") or "22%"
            _room_txt_a = (
                ret_format_money(float(_tax_room))
                if _tax_room is not None
                else "top bracket"
            )
            st.markdown("#### Leave retirement money as-is this year")
            st.caption(
                _md(
                    "You are **not** turning BrokerageLink (your 401k investment window) into "
                    "Roth (after-tax growth that can come out tax-free later). "
                    "No extra tax bill this year from conversions."
                )
            )
            _path_a_rows = [
                {
                    "What": "BrokerageLink stays pre-tax",
                    "In plain English": (
                        "Your workplace retirement account (401k) keeps growing as pre-tax money — "
                        "you pay tax later when you withdraw, not now."
                    ),
                    "Your numbers": ret_format_money(_bl_bal_a),
                },
                {
                    "What": "Extra tax this year",
                    "In plain English": (
                        "No Roth conversion this year, so there is no conversion tax bill from this path."
                    ),
                    "Your numbers": ret_format_money(0.0),
                },
                {
                    "What": "Unused room in current tax bracket",
                    "In plain English": (
                        "How much more taxable income you could take before jumping to the next "
                        f"federal tax bracket ({_bracket_lbl} now)."
                    ),
                    "Your numbers": (
                        f"{_room_txt_a} still in {_bracket_lbl}"
                        if _tax_room is not None
                        else _room_txt_a
                    ),
                },
                {
                    "What": "Best reason",
                    "In plain English": (
                        "Finish paying the second mortgage (HomeLoan) first, and avoid a cash tax bill this year."
                    ),
                    "Your numbers": "Finish Home equity / avoid cash tax",
                },
            ]
            st.dataframe(
                pd.DataFrame(_path_a_rows),
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Your numbers": st.column_config.Column("Your numbers", alignment="right"),
                },
            )

        elif _is_b:
            st.markdown("#### Path B — what if we move some to Roth?")
            st.caption(
                _md(
                    "Moving pre-tax 401k (workplace retirement) → Roth means you pay tax **now** "
                    "so growth can be tax-free later. "
                    "**Extra tax** = how much more federal tax this year. "
                    "**Tax cost per Roth $** ≈ how many cents of tax for each $1 moved. "
                    f"Full 401k balance uses live BrokerageLink "
                    f"**{ret_format_money(float(_tax_base.get('brokeragelink_balance') or 0))}**."
                )
            )

            _tax_rows = []
            for _r in _tax_scen:
                _room = _r.get("room_left")
                _tax_rows.append(
                    {
                        "What if": (
                            "Full 401k balance"
                            if _r["label"] == "full_401k_balance"
                            else (
                                "Fill current bracket"
                                if _r["label"] == "fill_bracket"
                                else (
                                    "Jump one bracket"
                                    if _r["label"] == "jump_one_bracket"
                                    else _r["label"]
                                )
                            )
                        ),
                        "Move to Roth": ret_format_money(float(_r["convert"])),
                        "New taxable income": ret_format_money(float(_r["new_taxable"])),
                        "Tax bracket before": _r["bracket_before"],
                        "Tax bracket after": _r["bracket_after"],
                        "Extra tax this year": ret_format_money(float(_r["extra_tax"])),
                        "Tax cost per Roth $": (
                            ret_format_pct(float(_r["tax_per_roth_dollar"]))
                            if float(_r["convert"]) > 0
                            else "—"
                        ),
                        "Room left in bracket": (
                            ret_format_money(float(_room))
                            if _room is not None
                            else "—"
                        ),
                    }
                )
            _tax_df = pd.DataFrame(_tax_rows)
            _tax_cfg = {
                c: st.column_config.Column(c, alignment="right")
                for c in (
                    "Move to Roth",
                    "New taxable income",
                    "Extra tax this year",
                    "Tax cost per Roth $",
                    "Room left in bracket",
                )
            }
            st.dataframe(
                _tax_df,
                use_container_width=True,
                hide_index=True,
                column_config=_tax_cfg,
            )
            with st.expander("How the taxable baseline is built"):
                st.markdown(
                    _md(
                        f"- Alex annualized gross: **{ret_format_money(float(_tax_base['alex_annualized_gross_base']))}** "
                        f"(year-to-date × 26/{int(_tax_base['pays_to_date_assumed'])})\n"
                        f"- Jordan flat: **{ret_format_money(float(_tax_base['secondary_flat_annual']))}**\n"
                        f"- Pretax 401k annualized: **{ret_format_money(float(_tax_base['pretax_401k_annualized']))}** "
                        f"(year-to-date × 26/pays)\n"
                        f"- AGI proxy (rough yearly income for tax planning): "
                        f"**{ret_format_money(float(_tax_base['agi_proxy']))}**\n"
                        f"- Standard deduction 2026 married filing jointly: "
                        f"**{ret_format_money(float(_tax_base['standard_deduction']))}**\n"
                        f"- Taxable income proxy: **{ret_format_money(float(_tax_base['taxable_proxy']))}**\n\n"
                        + "\n".join(f"- _{n}_" for n in (_tax_base.get("method_notes") or []))
                    )
                )

        else:  # Path C mega backdoor
            st.markdown("#### Path C — grow NEW money as Roth (mega backdoor)")
            _plan_feats = load_plan_features()
            _card = _plan_feats.get("card_copy") or {}
            _feats = _plan_feats.get("features") or {}
            _bl_bal = float(_tax_base.get("brokeragelink_balance") or 515916.24)
            st.success(
                _md(
                    f"**{_card.get('path_c_headline') or 'Mega backdoor: AVAILABLE'}** — "
                    f"{_card.get('mega_status') or 'Yes — after-tax + in-plan Roth conversion (SPD Jan 2026)'}"
                )
            )
            st.caption(
                _md(
                    "This is about **future paycheck dollars** you put in after-tax, then move to Roth "
                    "(after-tax growth that can come out tax-free later). "
                    "It is **not** turning today’s big pre-tax BrokerageLink pile into Roth "
                    "(that’s Path B)."
                )
            )
            _after_tax_status = (
                (_feats.get("after_tax_non_roth_contributions") or {}).get("status") or "Yes"
            )
            _in_plan_status = (
                (_feats.get("in_plan_roth_conversion") or {}).get("status") or "Yes"
            )
            _match_status = (
                (_feats.get("employer_match") or {}).get("status") or "100% of first 6%"
            )
            if _match_status.lower() in ("yes", "available"):
                _match_status = "100% of first 6%"
            _path_c_rows = [
                {
                    "Step": "1. Put after-tax dollars in the 401k",
                    "In plain English": (
                        "Money already taxed from your paycheck goes into the workplace "
                        "retirement account (401k)."
                    ),
                    "Status": (
                        f"{_after_tax_status} (SPD)"
                        if "SPD" not in str(_after_tax_status).upper()
                        else _after_tax_status
                    ),
                },
                {
                    "Step": "2. Move those dollars to Roth inside the plan (or to a Roth IRA)",
                    "In plain English": (
                        "Usually little extra tax if you move them soon after contributing."
                    ),
                    "Status": _in_plan_status,
                },
                {
                    "Step": "3. Keep today’s BrokerageLink pre-tax pile alone",
                    "In plain English": (
                        "Do not mix this path with converting the existing balance "
                        f"({ret_format_money(_bl_bal)} still pre-tax)."
                    ),
                    "Status": "Separate",
                },
                {
                    "Step": "4. Employer match",
                    "In plain English": (
                        "Company adds money (taxed later when withdrawn)."
                    ),
                    "Status": _match_status,
                },
            ]
            st.dataframe(
                pd.DataFrame(_path_c_rows),
                use_container_width=True,
                hide_index=True,
            )
            st.markdown(
                _md(
                    "**Do**\n"
                    "- Use future paycheck after-tax dollars, then move them to Roth soon.\n"
                    "- Keep today’s BrokerageLink pre-tax pile on its own track.\n\n"
                    "**Don’t**\n"
                    "- Treat the existing BrokerageLink balance as Roth.\n"
                    "- Mix this path with Path B (moving today’s big pre-tax balance to Roth)."
                )
            )
            with st.expander("SPD proof quotes (short)", expanded=False):
                _proofs = []
                for _key, _label in (
                    ("after_tax_non_roth_contributions", "After-tax"),
                    ("in_plan_roth_conversion", "In-plan Roth conversion"),
                    ("in_service_withdrawal_after_tax_to_roth_ira", "After-tax → Roth IRA"),
                    ("employer_match", "Employer match"),
                    ("caps_waiting_max_deferrals_first", "Deferral spillover → after-tax"),
                ):
                    _p = (_feats.get(_key) or {}).get("proof")
                    if _p:
                        _proofs.append(f"**{_label}:** _{_p}_")
                st.markdown(_md("\n\n".join(_proofs)))
                _src = _plan_feats.get("source") or {}
                st.caption(
                    f"Source: {_src.get('document', 'SPD')} · effective {_src.get('effective', '?')} "
                    f"· as of {_src.get('as_of', '?')}"
                )

        st.markdown("#### Worth it?")
        st.caption(
            _md(
                "Right now we lean **no** on big Roth moves until the second mortgage is paid down."
            )
        )
        st.markdown(
            f"""
<div style="border-radius:16px;padding:1rem 1.05rem 0.9rem;
  background:linear-gradient(160deg,#f7f4ef 0%,#fbf8f3 100%);
  border:1px solid #e2d5c3;margin:0.25rem 0 0.75rem 0;">
  <div style="font-size:1.05rem;font-weight:750;color:#7a4a1e;">
    {_tax_verdict.get('headline') or _tax_verdict.get('verdict')}
  </div>
</div>
            """,
            unsafe_allow_html=True,
        )
        for _b in (_tax_verdict.get("bullets") or [])[:3]:
            st.markdown(f"- {_md(_b)}")

    except Exception as _tax_exc:
        st.warning(f"Tax layer unavailable: {_tax_exc}")


elif page == "Rules":
    st.title("Recurring rules")
    st.caption("Edit day-of-month / biweekly rules. Amounts: expenses negative, income positive.")
    st.caption(
        "Due dates learn from bank CSV/screenshots; Mortgage locked to day 11; AT&T & Water are manual."
    )

    rdf = pd.DataFrame(
        [
            {
                "id": r["id"],
                "category": r["category"],
                "cadence": r["cadence"],
                "day": r["day_of_month"],
                "amount": r["amount"],
                "anchor": r.get("anchor_date") or "",
                "start": r.get("start_date") or "",
                "end": r.get("end_date") or "",
                "enabled": r["enabled"],
                "by_year": json.dumps(r.get("amount_by_year") or {}),
            }
            for r in rules
        ]
    )
    st.dataframe(rdf, use_container_width=True, height=360)

    with st.expander("Learned due dates", expanded=False):
        prefs = load_payment_preferences()
        st.caption(
            "CSV/screenshot dates drive forecast timing. "
            f"Manual pay: {', '.join(prefs.get('manual_pay') or [])}. "
            f"Locked: {prefs.get('locked_dom')}."
        )
        learned_data = None
        if LEARNED_PATH.exists():
            try:
                learned_data = json.loads(LEARNED_PATH.read_text(encoding="utf-8"))
            except Exception:
                learned_data = None
        if st.button("Refresh learned dates from actuals", key="refresh_learned_doms"):
            learned_data = learn_from_actuals(conn)
            st.success(
                f"Refreshed {LEARNED_PATH.name} · "
                f"{(learned_data.get('summary') or {}).get('eligible_to_apply', 0)} eligible shifts"
            )
        if learned_data and learned_data.get("categories"):
            rows = []
            for cat, s in learned_data["categories"].items():
                rows.append(
                    {
                        "category": cat,
                        "current DOM": s.get("current_dom"),
                        "learned DOM": s.get("learned_dom"),
                        "samples": s.get("samples"),
                        "last seen": s.get("last_seen"),
                        "auto/manual": s.get("pay_mode"),
                        "stdev": s.get("stdev"),
                        "locked": s.get("locked"),
                    }
                )
            st.dataframe(pd.DataFrame(rows), use_container_width=True, height=320)
        else:
            st.info("No learned file yet — refresh after a bank CSV import.")
        if st.button("Apply learned dates to forecast", type="primary", key="apply_learned_doms"):
            if learned_data is None and LEARNED_PATH.exists():
                learned_data = json.loads(LEARNED_PATH.read_text(encoding="utf-8"))
            if learned_data is None:
                learned_data = learn_from_actuals(conn)
            report = apply_learned_doms(conn, dry_run=False, min_samples=3, learned=learned_data)
            n = report.get("n_changed_rules") or 0
            if n:
                st.success(f"Updated {n} rule day-of-month value(s).")
                for ch in report.get("changes") or []:
                    st.write(
                        f"- **{ch['category']}** (rule {ch['rule_id']}): "
                        f"{ch['old']} → {ch['new']} (n={ch['samples']})"
                    )
                st.cache_resource.clear()
                st.rerun()
            else:
                st.info("No DOM changes to apply (locked / low samples / already matched).")

    st.subheader("Edit / add rule")
    with st.form("rule_form"):
        cols = st.columns(4)
        rid = cols[0].number_input("id (0=new)", min_value=0, value=0, step=1)
        category = cols[1].text_input("category", value="Home Mortgage")
        cadence = cols[2].selectbox("cadence", ["monthly_dom", "biweekly"])
        day = cols[3].number_input("day_of_month", min_value=0, max_value=31, value=11)
        cols2 = st.columns(4)
        amount = cols2[0].number_input("amount", value=-950.00, step=10.0, format="%.2f")
        anchor = cols2[1].text_input("anchor_date (biweekly)", value="2026-09-11")
        start_d = cols2[2].text_input("start_date", value="2026-09-01")
        end_d = cols2[3].text_input("end_date", value="")
        enabled = st.checkbox("enabled", value=True)
        by_year_txt = st.text_input("amount_by_year JSON", value="{}")
        submitted = st.form_submit_button("Save rule")
        if submitted:
            try:
                aby = json.loads(by_year_txt or "{}")
            except json.JSONDecodeError:
                st.error("Invalid amount_by_year JSON")
                aby = None
            if aby is not None:
                payload = {
                    "category": category,
                    "label": category,
                    "day_of_month": int(day) if cadence == "monthly_dom" else None,
                    "amount": float(amount),
                    "amount_by_year": aby,
                    "cadence": cadence,
                    "anchor_date": anchor or None,
                    "interval_days": 14,
                    "start_date": start_d or None,
                    "end_date": end_d or None,
                    "enabled": enabled,
                }
                if rid:
                    payload["id"] = int(rid)
                new_id = db.upsert_rule(conn, payload)
                st.success(f"Saved rule id={new_id}")
                st.rerun()

    del_id = st.number_input("Delete rule id", min_value=0, value=0, step=1, key="del_rule")
    if st.button("Delete rule") and del_id:
        db.delete_rule(conn, int(del_id))
        st.success("Deleted")
        st.rerun()

# ---------- MONTH DETAIL ----------
elif page == "Month detail":
    st.title("Month detail — daily EOD + flows")
    st.caption(
        "Day-forward: default month = start_date month; prior days before "
        f"**{settings['start_date']}** are hidden unless you expand them."
    )
    res = project(
        settings["start_date"],
        settings["end_date"],
        settings["start_balance"],
        rules,
        planned,
        actuals,
        None,
        settings["warning_threshold"],
        suppress_rules_through=settings.get("suppress_rules_through"),
    )
    months = sorted({(d["date"].year, d["date"].month) for d in res["daily"]})
    labels = [f"{y}-{m:02d}" for y, m in months]
    # Default to start_date month (day-forward focus)
    start = settings["start_date"]
    default_label = f"{start.year}-{start.month:02d}"
    default_idx = labels.index(default_label) if default_label in labels else 0
    pick = st.selectbox("Month", labels, index=default_idx)
    yy, mm = map(int, pick.split("-"))
    days = [d for d in res["daily"] if d["date"].year == yy and d["date"].month == mm]

    show_prior = st.checkbox(
        "Show days before start_date (collapse prior by default)",
        value=False,
        key="month_show_prior",
    )
    if not show_prior:
        hidden = [d for d in days if d["date"] < start]
        days_view = [d for d in days if d["date"] >= start]
        if hidden:
            st.info(
                f"Day-forward: hiding {len(hidden)} day(s) before {start.isoformat()}. "
                "Check the box above to expand prior days."
            )
    else:
        days_view = days

    # Breach autopsy at top when this month goes red
    month_meta = next(
        (m for m in res["months"] if m["year"] == yy and m["month"] == mm), None
    )
    if month_meta and ((month_meta.get("days_negative") or 0) > 0 or month_meta.get("first_breach")):
        auto = breach_autopsy(res["daily"], yy, mm)
        st.subheader("What caused the red?")
        if auto:
            mit = mitigation_suggestions(
                res["daily"],
                yy,
                mm,
                start_date=settings["start_date"],
                end_date=settings["end_date"],
                start_balance=settings["start_balance"],
                rules=rules,
                planned=planned,
                actuals=actuals,
                warning_threshold=settings["warning_threshold"],
                suppress_rules_through=settings.get("suppress_rules_through"),
                autopsy=auto,
            )
            _render_breach_autopsy(
                auto,
                key_prefix=f"month_{yy}_{mm:02d}",
                mitigation=mit,
                conn=conn,
            )
        else:
            st.caption("Month flagged red but autopsy found no breach day.")

    daily_rows = []
    flow_rows = []
    for d in days_view:
        daily_rows.append(
            {
                "date": d["date"].isoformat(),
                "flow_sum": d["flow_sum"],
                "eod": d["eod"],
                "neg": d["negative"],
                "warn": d["warning"],
            }
        )
        for f in d["flows"]:
            flow_rows.append(
                {
                    "date": d["date"].isoformat(),
                    "category": f.category,
                    "amount": f.amount,
                    "label": f.label,
                    "source": f.source,
                }
            )
    st.subheader("Daily EOD")
    if not daily_rows:
        st.warning(
            "No days in view for this month under day-forward filter "
            "(month may be entirely before start_date)."
        )
    else:
        st.dataframe(
            pd.DataFrame(daily_rows).style.format({"flow_sum": "${:,.2f}", "eod": "${:,.2f}"}),
            use_container_width=True,
            height=400,
        )
    st.subheader("Flows")
    st.dataframe(
        pd.DataFrame(flow_rows).style.format({"amount": "${:,.2f}"}),
        use_container_width=True,
        height=320,
    )

    with st.expander("Day-forward / day-grid stub", expanded=False):
        st.markdown(
            """
- **Day-forward rule:** boards default to `settings.start_date` (today / seam **2026-09-12**);
  prior calendar days are collapsed.
- Per-day **category expand grid** (spend by parent on each day) is not built yet —
  use **Household spending & income insights** for parent spend charts + trends.
            """
        )

# ---------- SCENARIOS (multi-scenario sandbox) ----------
elif page == "Scenarios":
    st.title("Scenario sandbox — compare alternatives")
    st.markdown(
        """
Build **named scenarios** as deltas on the baseline (income/expense changes, one-offs,
bonus → debt redirects, rule overrides). Compare Baseline vs A vs B across year and
full-horizon metrics. Duplicate a scenario to tweak quickly.
"""
    )

    # --- Comparison ---
    st.subheader("Side-by-side comparison")
    selected_names = st.multiselect(
        "Scenarios to compare (Baseline always included)",
        options=[s["name"] for s in scenarios],
        default=[s["name"] for s in scenarios[:3]],
    )
    selected = [s for s in scenarios if s["name"] in selected_names]
    cmp = compare_scenarios(
        settings["start_date"],
        settings["end_date"],
        settings["start_balance"],
        rules,
        planned,
        actuals,
        selected,
        settings["warning_threshold"],
        suppress_rules_through=settings.get("suppress_rules_through"),
    )

    # Horizon cards
    cards = st.columns(len(cmp))
    for col, item in zip(cards, cmp):
        sm = item["summary"]
        with col:
            st.markdown(f"### {item['name']}")
            st.metric("Ending bal", money(sm["ending_balance"]))
            st.metric("Min EOD", money(sm["min_eod"]))
            st.write(f"First breach: **{sm['first_breach'] or 'None'}**")
            st.write(f"Neg days: **{sm['negative_days']}** · Warn: **{sm['warning_days']}**")

    # Comparison table — horizon + per year
    comp_rows = []
    for item in cmp:
        sm = item["summary"]
        row = {
            "Scenario": item["name"],
            "Horizon ending": sm["ending_balance"],
            "Horizon min EOD": sm["min_eod"],
            "First breach": sm["first_breach"].isoformat() if sm["first_breach"] else "",
            "Neg days": sm["negative_days"],
            "Warn days": sm["warning_days"],
        }
        for y in item["years"]:
            yr = y["year"]
            row[f"{yr} ending"] = y["ending_balance"]
            row[f"{yr} min"] = y["min_eod"]
            row[f"{yr} red mo"] = y["red_months"]
            row[f"{yr} breach"] = y["first_breach"].isoformat() if y["first_breach"] else ""
        comp_rows.append(row)
    cdf = pd.DataFrame(comp_rows)
    money_cols = [c for c in cdf.columns if "ending" in c.lower() or "min" in c.lower()]
    fmt = {c: "${:,.2f}" for c in money_cols}
    st.dataframe(cdf.style.format(fmt), use_container_width=True)

    st.divider()
    st.subheader("Manage scenarios")

    # List + duplicate / delete
    for sc in scenarios:
        with st.expander(f"{sc['name']} (id={sc['id']})", expanded=False):
            st.write(sc.get("description") or "")
            st.json(sc.get("deltas") or [])
            b1, b2, b3 = st.columns(3)
            if b1.button("Duplicate", key=f"dup_{sc['id']}"):
                new_id = db.duplicate_scenario(conn, sc["id"])
                st.success(f"Duplicated → id={new_id}")
                st.rerun()
            if b2.button("Delete", key=f"del_{sc['id']}"):
                db.delete_scenario(conn, sc["id"])
                st.rerun()

    st.subheader("Create / update scenario")
    with st.form("scenario_form"):
        sid = st.number_input("Scenario id (0 = new)", min_value=0, value=0, step=1)
        name = st.text_input("Name", value="New scenario")
        desc = st.text_area("Description", value="")
        st.markdown("**Add lever (delta)** — submit form to save scenario with the deltas JSON below.")
        kind = st.selectbox(
            "Quick-add kind (appended into JSON editor on next save if you paste)",
            [
                "one_off",
                "income_change",
                "expense_change",
                "redirect",
                "rule_override",
                "disable_rule",
            ],
        )
        st.caption(
            "Edit the deltas JSON directly. Kinds: one_off, income_change, expense_change, "
            "redirect, rule_override, disable_rule. Modes for change: add | pct | set."
        )
        default_deltas = [
            {
                "kind": "one_off",
                "label": "Example purchase",
                "category": "Shopping",
                "amount": -5000.0,
                "on_date": "2027-03-15",
                "mode": "add",
            }
        ]
        if sid:
            existing = db.get_scenario(conn, int(sid))
            if existing:
                default_deltas = existing["deltas"]
                # name/desc won't auto-fill outside form easily; user can copy
        deltas_txt = st.text_area("deltas JSON", value=json.dumps(default_deltas, indent=2), height=220)
        save = st.form_submit_button("Save scenario")
        if save:
            try:
                deltas = json.loads(deltas_txt)
                # validate parseable as ScenarioDelta
                for d in deltas:
                    ScenarioDelta.from_dict(d)
                payload = {"name": name, "description": desc, "deltas": deltas}
                if sid:
                    payload["id"] = int(sid)
                new_id = db.save_scenario(conn, payload)
                st.success(f"Saved scenario id={new_id}")
                st.rerun()
            except Exception as e:
                st.error(f"Could not save: {e}")

    st.subheader("Baseline planned one-offs (shared across scenarios)")
    st.caption("These sit on the baseline (not scenario-specific). Prefer scenario deltas for what-ifs.")
    with st.form("planned_form"):
        pc = st.columns(4)
        pdate = pc[0].date_input("date", value=date(2027, 6, 1))
        pamt = pc[1].number_input("amount", value=-1000.0, step=100.0)
        pcat = pc[2].text_input("category", value="Planned")
        plabel = pc[3].text_input("label", value="")
        if st.form_submit_button("Add planned item"):
            db.add_planned(
                conn,
                {"date": pdate.isoformat(), "amount": pamt, "category": pcat, "label": plabel},
            )
            st.rerun()
    if planned:
        st.dataframe(pd.DataFrame(planned), use_container_width=True)


# ---------- IMPORT ----------
elif page == "Import":
    st.title("Import — bank CSV → actuals")
    st.caption(
        "Due dates learn from bank CSV/screenshots; Mortgage locked to day 11; AT&T & Water are manual."
    )
    st.markdown(
        """
Upload a bank checking CSV (columns: Details, Posting Date, Description, Amount, Type, Balance).
Rows are stored in **actuals** with transaction **label** (Description) and Excel **category** buckets
via keyword merchant maps. Prior imports tagged `source=bank_csv` are replaced; rules/scenarios stay.

CLI equivalent:

```bash
python scripts/import_bank_csv.py /path/to/chase.csv
```
"""
    )
    n_actuals = len(all_actuals)
    n_csv = sum(1 for a in all_actuals if (a.get("source") or "") == CSV_SOURCE)
    n_black = sum(1 for a in all_actuals if (a.get("source") or "") == BLACK_CARD_SOURCE)
    st.caption(
        f"Current actuals: **{n_actuals}** total · **{n_csv}** from bank_csv · "
        f"**{n_black}** from {BLACK_CARD_SOURCE}"
    )

    uploaded = st.file_uploader("bank CSV", type=["csv"])
    default_hint = (
        "/home/box/agent-data/agents/.../attachments/*.csv or any Chase export"
    )
    path_in = st.text_input("Or path on server", value="", placeholder=default_hint)
    replace = st.checkbox("Replace previous bank_csv actuals", value=True)

    if st.button("Run import", type="primary"):
        try:
            if uploaded is not None:
                import io
                raw = uploaded.getvalue().decode("utf-8-sig")
                report = import_csv(
                    conn, io.StringIO(raw), replace_csv_actuals=replace
                )
            elif path_in.strip():
                report = import_csv(
                    conn, path_in.strip(), replace_csv_actuals=replace
                )
            else:
                st.error("Provide a file upload or server path")
                report = None
            if report:
                # Keep projection seam settings stable
                db.set_setting(conn, "start_balance", "5000.00")
                db.set_setting(conn, "start_date", "2026-09-12")
                db.set_setting(conn, "end_date", "2029-09-12")
                settings_now = db.get_settings(conn)
                write_import_report(
                    report,
                    {
                        "start_balance": settings_now["start_balance"],
                        "start_date": settings_now["start_date"].isoformat(),
                        "end_date": settings_now["end_date"].isoformat(),
                    },
                    Path(__file__).resolve().parent / "data" / "import_report.md",
                )
                st.success(
                    f"Imported {report['rows_imported']} rows · "
                    f"{report['pct_categorized']}% categorized · "
                    f"{report['uncategorized']} uncategorized"
                )
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("Rows", report["rows_imported"])
                c2.metric("% categorized", f"{report['pct_categorized']}%")
                c3.metric("Money in", money(report["total_in"]))
                c4.metric("Money out", money(report["total_out"]))
                st.subheader("Top uncategorized merchants")
                if report["top_uncategorized"]:
                    st.dataframe(
                        pd.DataFrame(
                            report["top_uncategorized"], columns=["merchant", "count"]
                        ),
                        use_container_width=True,
                    )
                else:
                    st.write("None")
                st.subheader("Top categories by spend")
                st.dataframe(
                    pd.DataFrame(
                        report["top_categories_by_spend"], columns=["category", "spend"]
                    ),
                    use_container_width=True,
                )
                ddl = report.get("due_date_learn") or {}
                if ddl.get("error"):
                    st.warning(f"Due-date learn skipped: {ddl['error']}")
                elif ddl:
                    st.caption(
                        f"Due-date learn: {ddl.get('applied_rule_changes', 0)} rule DOM updates · "
                        f"wrote data/due_date_learned.json"
                    )
                st.caption("Wrote data/import_report.md and refreshed merchant maps.")
                st.cache_resource.clear()
        except Exception as e:
            st.error(f"Import failed: {e}")

    st.divider()
    st.subheader("Rewards Card card CSV")
    n_black = sum(1 for a in all_actuals if (a.get("source") or "") == BLACK_CARD_SOURCE)
    st.caption(
        _md(
            f"Partner allowance / family card (••••1234). "
            f"**{n_black}** rows tagged `{BLACK_CARD_SOURCE}`. "
            "Replace does **not** use the checking checkbox and never clears bank_csv."
        )
    )
    _render_black_card_import_box(conn, key_prefix="import_black")

    st.divider()
    st.subheader("Merchant maps")
    maps = db.list_merchant_maps(conn)
    st.caption(f"{len(maps)} patterns in DB (also saved to data/merchant_map.json)")
    if maps:
        st.dataframe(pd.DataFrame(maps), use_container_width=True, height=240)

    report_path = Path(__file__).resolve().parent / "data" / "import_report.md"
    if report_path.exists():
        with st.expander("Last import_report.md"):
            st.markdown(report_path.read_text(encoding="utf-8"))

# ---------- SETTINGS ----------
elif page == "Settings":
    st.title("Settings")
    with st.form("settings_form"):
        sd = st.date_input("Start date", value=settings["start_date"])
        ed = st.date_input("Horizon end", value=settings["end_date"])
        bal = st.number_input("Starting checking balance", value=float(settings["start_balance"]), step=100.0, format="%.2f")
        warn = st.number_input("Warning threshold (EOD <)", value=float(settings["warning_threshold"]), step=50.0)
        breach = st.number_input("Breach threshold (EOD <)", value=float(settings["breach_threshold"]), step=50.0)
        _sup = settings.get("suppress_rules_through")
        suppress_on = st.checkbox(
            "Suppress recurring rules through a date (use Budget workbook planned for current month)",
            value=_sup is not None,
        )
        suppress_day = st.date_input(
            "suppress_rules_through",
            value=_sup or settings["start_date"],
            help="Rules do not fire on/before this date; planned_items cover those days instead.",
        )
        if st.form_submit_button("Save settings"):
            db.save_settings(
                conn,
                {
                    "start_date": sd,
                    "end_date": ed,
                    "start_balance": bal,
                    "warning_threshold": warn,
                    "breach_threshold": breach,
                    "suppress_rules_through": suppress_day if suppress_on else None,
                },
            )
            st.success("Saved")
            st.rerun()

    st.divider()
    st.subheader("Net worth cards (optional)")
    st.caption(
        "Brokerage / Fidelity and Savings balances for the pictorial cards on "
        "Dashboard and Bills. Leave blank until you have figures — cards show an "
        "em dash, not \\$0. Does **not** change checking start balance or the cash twin."
    )
    _nw = load_snapshot()

    def _nw_parse(raw: str):
        s = (raw or "").strip().replace(",", "").replace("$", "")
        if not s:
            return None
        return float(s)

    with st.form("net_worth_form"):
        fid_txt = st.text_input(
            "Brokerage / Fidelity balance",
            value=(
                f"{_nw['fidelity_brokerage_balance']:.2f}"
                if _nw.get("fidelity_brokerage_balance") is not None
                else ""
            ),
            placeholder="Leave blank = Not set yet",
            key="nw_fid_bal",
        )
        sav_txt = st.text_input(
            "Savings balance",
            value=(
                f"{_nw['savings_balance']:.2f}"
                if _nw.get("savings_balance") is not None
                else ""
            ),
            placeholder="Leave blank = Not set yet",
            key="nw_sav_bal",
        )
        as_of_in = st.text_input(
            "Balances as of (optional date label)",
            value=_nw.get("balances_as_of") or "",
            placeholder="e.g. 2026-09-12",
            key="nw_as_of",
        )
        if st.form_submit_button("Save net-worth balances"):
            try:
                fid_val = _nw_parse(fid_txt)
                sav_val = _nw_parse(sav_txt)
            except ValueError:
                st.error("Balances must be numbers (or blank).")
            else:
                save_snapshot(
                    fidelity_brokerage_balance=fid_val,
                    savings_balance=sav_val,
                    balances_as_of=as_of_in.strip() or None,
                )
                db.set_setting(
                    conn,
                    "fidelity_brokerage_balance",
                    "" if fid_val is None else fid_val,
                )
                db.set_setting(
                    conn,
                    "savings_balance",
                    "" if sav_val is None else sav_val,
                )
                db.set_setting(conn, "balances_as_of", as_of_in.strip() if as_of_in else "")
                st.success("Net-worth card balances saved")
                st.rerun()

    st.divider()
    st.subheader("Seed import")
    seed_path = resolve_seed_dir()
    st.write(f"Detected seed: `{seed_path}`" if seed_path else "No seed directory found.")
    meta = conn.execute("SELECT key, value FROM settings WHERE key LIKE 'seed%' OR key IN ('import_summary','mortgage_policy','secondary_2028_policy')").fetchall()
    if meta:
        st.json({r["key"]: r["value"] for r in meta})
    prefer_mortgage = st.checkbox(
        "Prefer single mortgage (Loans!X11 −950.00) — cleaned what-if, not Excel-parity",
        value=False,
    )
    inherit_d = st.checkbox("Jordan 2028 inherit 2027 (\\$1500) — Excel cell is blank", value=False)
    if st.button("Re-import seed (reset rules/scenarios; keeps bank_csv actuals)"):
        if not seed_path:
            st.error("No seed found")
        else:
            summary = import_seed(
                conn, seed_path, prefer_single_mortgage=prefer_mortgage, secondary_2028_inherit=inherit_d, reset=True
            )
            st.success(summary)
            st.cache_resource.clear()
            st.rerun()

    st.caption(
        "Default re-import is **Excel-parity** (double mortgage through 2027-12, wife −2500 "
        "through Feb 2027, side_gig Other Income stamps, HOA/presser overlays). "
        "Live seam restored to **\\$4,525.32** on **2026-09-12** with Sep Budget workbook override. "
        "Bank CSV actuals are kept. Single-mortgage is also a named scenario."
    )
