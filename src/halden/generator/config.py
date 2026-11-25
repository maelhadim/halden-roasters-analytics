"""Every parameter of the synthetic Halden Roasters world, in one place.

Nothing here is real company data. The numbers are chosen to be plausible for
a small European coffee subscription business, and they are deliberately
written down so the later projects can be checked against the truth.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

SEED = 20250630

DATA_START = date(2023, 1, 1)
DATA_END = date(2025, 6, 30)

# Business events that the later projects have to discover in the data.
CRM_MIGRATION_DATE = date(2023, 3, 13)
PROCESSOR_SCHEMA_CHANGE = date(2024, 7, 1)
SHOP_DATE_FORMAT_BUG = (date(2024, 2, 5), date(2024, 2, 11))
WAREHOUSE_INCIDENT = (date(2024, 11, 11), date(2024, 11, 24))  # Hamburg site only
PRICE_INCREASE_DATE = date(2025, 2, 1)
EXPERIMENT_ID = "RET-2025-04"
EXPERIMENT_ENROL = (date(2025, 4, 1), date(2025, 4, 30))
EXPERIMENT_LOG_OUTAGE = (date(2025, 4, 9), date(2025, 4, 11))


@dataclass(frozen=True)
class Country:
    code: str
    share: float
    locale: str
    currency: str
    site: str           # fulfilment site that ships to this country
    vat_rate: float     # simplified rate for roasted coffee; an assumption, not tax advice
    transit_days: tuple[int, int]


COUNTRIES = (
    Country("GB", 0.55, "en_GB", "GBP", "MAN", 0.00, (1, 2)),
    Country("IE", 0.10, "en_IE", "EUR", "HAM", 0.00, (3, 5)),
    Country("DE", 0.20, "de_DE", "EUR", "HAM", 0.07, (1, 3)),
    Country("NL", 0.15, "nl_NL", "EUR", "HAM", 0.09, (2, 3)),
)
COUNTRY_BY_CODE = {c.code: c for c in COUNTRIES}


@dataclass(frozen=True)
class Plan:
    code: str
    share: float
    # Prices include VAT, as shown to the customer. (old, new) around the price increase.
    gbp: tuple[float, float]
    eur: tuple[float, float]
    # The cheapest plan attracts the most price-sensitive customers.
    price_rise_churn_mult: float


PLANS = (
    Plan("CLASSIC_250", 0.55, (11.50, 12.50), (13.50, 14.90), 1.9),
    Plan("EXPLORER_2X250", 0.30, (21.00, 22.50), (24.50, 26.50), 1.4),
    Plan("ESPRESSO_1KG", 0.15, (32.00, 34.00), (37.00, 39.50), 1.3),
)
PLAN_BY_CODE = {p.code: p for p in PLANS}

FREQUENCIES = (("MONTHLY", 0.7), ("FORTNIGHTLY", 0.3))

# One-off shop products: (sku, gbp, eur)
PRODUCTS = (
    ("BEANS_250_SINGLE_ORIGIN", 8.50, 9.90),
    ("BEANS_1KG_HOUSE", 26.00, 30.00),
    ("GIFT_BOX_3X250", 25.00, 29.00),
    ("HAND_GRINDER", 39.00, 45.00),
    ("POUR_OVER_KIT", 29.00, 34.00),
    ("MUG_SET", 18.00, 21.00),
)
SHIPPING_FEE = {"GBP": 3.95, "EUR": 4.50}
FREE_SHIPPING_FROM = {"GBP": 25.00, "EUR": 29.00}


@dataclass(frozen=True)
class Volumes:
    legacy_active_subscribers: int = 4200   # active on 1 Jan 2023, from before the data window
    signups_per_day: float = 11.0           # at the start of 2023, before seasonality
    signup_growth_per_month: float = 0.012
    guests_per_day: float = 3.5
    guest_registers_prob: float = 0.30
    promo_share: float = 0.35
    promo_share_january: float = 0.60
    parallel_account_prob: float = 0.02     # an existing subscriber opens a second account
    oneoff_per_cycle: float = 0.04


SEASONALITY = {1: 1.4, 2: 1.0, 3: 1.0, 4: 1.0, 5: 0.95, 6: 0.9,
               7: 0.8, 8: 0.8, 9: 1.0, 10: 1.05, 11: 1.3, 12: 1.6}


@dataclass(frozen=True)
class Churn:
    base_per_cycle: dict = field(default_factory=lambda: {"MONTHLY": 0.045, "FORTNIGHTLY": 0.022})
    tenure_mult: tuple = ((3, 1.8), (6, 1.2), (12, 1.0), (10**6, 0.7))  # (max cycle index, mult)
    promo_mult: float = 1.5
    late_this_cycle_mult: float = 2.2
    two_late_recent_mult: float = 3.0
    price_rise_window_days: int = 90
    nl_mult: float = 1.1
    winback_prob: float = 0.12
    winback_new_account_prob: float = 0.55


@dataclass(frozen=True)
class Payments:
    first_attempt_success: float = 0.965
    retry_success: tuple = (0.60, 0.50)     # attempts 2 and 3, 3 and 6 days after the first
    oneoff_first_attempt_success: float = 0.98
    fee_pct: float = 0.014
    fee_fixed: float = 0.20
    goodwill_refund_prob: float = 0.008
    chargeback_prob: float = 0.0015
    chargeback_fee: float = 15.00


@dataclass(frozen=True)
class Fulfilment:
    late_prob: float = 0.05
    late_prob_peak: float = 0.12            # 1 to 23 December
    late_prob_incident: float = 0.45
    lost_prob: float = 0.004


@dataclass(frozen=True)
class Experiment:
    min_tenure_days: int = 60
    treatment_share: float = 0.5
    discount_pct: float = 0.30
    discounted_orders: int = 3
    # True effect, used only to simulate outcomes. Project 5 has to estimate it blind.
    high_risk_threshold: float = 0.08       # per-cycle churn probability before treatment
    relative_reduction_high_risk: float = 0.40
    relative_reduction_low_risk: float = 0.12
    log_loss_share_in_outage: float = 0.35  # treatment events lost while the logger was down


VOLUMES = Volumes()
CHURN = Churn()
PAYMENTS = Payments()
FULFILMENT = Fulfilment()
EXPERIMENT = Experiment()
