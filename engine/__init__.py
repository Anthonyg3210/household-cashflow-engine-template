"""Household Cashflow Engine — projection engine."""
from .project import (
    project,
    month_metrics,
    compare_scenarios,
    ScenarioDelta,
    format_pitfall_ribbon,
    pitfall_months_by_year,
    year_pitfall_scorecard,
    filter_months_for_year,
    year_scorecard_kpis,
    breach_autopsy,
)
from .mitigation import (
    mitigation_suggestions,
    category_nature,
    load_flexibility_config,
    apply_mitigation_to_planned,
    apply_mitigation_db,
)

__all__ = [
    "project",
    "month_metrics",
    "compare_scenarios",
    "ScenarioDelta",
    "format_pitfall_ribbon",
    "pitfall_months_by_year",
    "year_pitfall_scorecard",
    "filter_months_for_year",
    "year_scorecard_kpis",
    "breach_autopsy",
    "mitigation_suggestions",
    "category_nature",
    "load_flexibility_config",
    "apply_mitigation_to_planned",
    "apply_mitigation_db",
]
