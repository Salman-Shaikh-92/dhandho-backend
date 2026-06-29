"""
Dhandho AI — ai_engine/agents/roi_agent.py

ROI Calculation Agent
---------------------
Pure Python — no LLM calls required.

Calculates:
  • ROI percentage
  • Monthly net profit
  • Payback period (months to recoup first month's investment)

Formula reference:
  ROI (%) = ((monthly_savings - monthly_cost) / monthly_cost) × 100
  Net Profit ($) = monthly_savings - monthly_cost
  Payback Period = monthly_cost / monthly_savings  (months)
"""

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public function
# ---------------------------------------------------------------------------
def calculate_roi(
    monthly_cost: float,
    monthly_savings: float,
) -> Dict[str, Any]:
    """
    Calculates ROI metrics for a recommended automation tool.

    Args:
        monthly_cost:    Estimated monthly subscription / implementation cost ($).
        monthly_savings: Estimated monthly savings the tool delivers ($).

    Returns:
        A dict with the following keys:
          - ``monthly_cost``          (float) — input cost, rounded to 2dp
          - ``monthly_savings``       (float) — input savings, rounded to 2dp
          - ``roi_percentage``        (float) — percentage return on investment
          - ``monthly_net_profit``    (float) — net monthly gain after cost
          - ``payback_period_months`` (float | None) — months to break even
                                                       (None if cost is 0)
          - ``annual_net_profit``     (float) — net_profit × 12
          - ``is_profitable``         (bool)  — True when savings > cost

    Raises:
        ValueError: If either argument is negative.
    """
    if monthly_cost < 0:
        raise ValueError(f"monthly_cost must be ≥ 0, got {monthly_cost}")
    if monthly_savings < 0:
        raise ValueError(f"monthly_savings must be ≥ 0, got {monthly_savings}")

    monthly_net_profit: float = monthly_savings - monthly_cost
    annual_net_profit: float = monthly_net_profit * 12
    is_profitable: bool = monthly_net_profit > 0

    # ── ROI % ──────────────────────────────────────────────────────────
    if monthly_cost == 0:
        # Tool is free — ROI is theoretically infinite; represent as None
        roi_percentage: Optional[float] = None
        logger.warning(
            "ROIAgent: monthly_cost is 0; ROI percentage is undefined (infinite)."
        )
    else:
        roi_percentage = round(
            (monthly_net_profit / monthly_cost) * 100, 2
        )

    # ── Payback period ─────────────────────────────────────────────────
    if monthly_cost == 0:
        payback_period_months: Optional[float] = 0.0   # Already paid off
    elif monthly_savings == 0:
        payback_period_months = None   # Never recoups the cost
    else:
        payback_period_months = round(monthly_cost / monthly_savings, 2)

    result = {
        "monthly_cost": round(monthly_cost, 2),
        "monthly_savings": round(monthly_savings, 2),
        "roi_percentage": roi_percentage,
        "monthly_net_profit": round(monthly_net_profit, 2),
        "annual_net_profit": round(annual_net_profit, 2),
        "payback_period_months": payback_period_months,
        "is_profitable": is_profitable,
    }

    logger.info(
        "ROIAgent: cost=$%.2f  savings=$%.2f  ROI=%.2f%%  net=$%.2f/mo",
        monthly_cost,
        monthly_savings,
        roi_percentage if roi_percentage is not None else 0,
        monthly_net_profit,
    )

    return result
