"""Ordered SEC aliases. Resolve per period/accession, never globally by tag.

First listed concept wins within a filing. Conflicting aliases produce a warning;
conflicting duplicates of the same concept are invalid. Different filing vintages
and durations remain separate source facts. No arithmetic inference is performed.
"""

from collections.abc import Mapping
from types import MappingProxyType

SEC_CONCEPTS: Mapping[str, tuple[str, ...]] = MappingProxyType(
    {
        "revenue": (
            "RevenueFromContractWithCustomerExcludingAssessedTax",
            "Revenues",
            "SalesRevenueNet",
        ),
        "gross_profit": ("GrossProfit",),
        "operating_income": ("OperatingIncomeLoss",),
        "net_income": ("NetIncomeLoss",),
        "operating_cash_flow": ("NetCashProvidedByUsedInOperatingActivities",),
        "capital_expenditures": ("PaymentsToAcquirePropertyPlantAndEquipment",),
        "cash_and_equivalents": ("CashAndCashEquivalentsAtCarryingValue",),
        "total_assets": ("Assets",),
        "total_liabilities": ("Liabilities",),
        "stockholders_equity": ("StockholdersEquity",),
    }
)
