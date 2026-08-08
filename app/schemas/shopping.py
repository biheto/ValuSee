from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class ShoppingProductInput(BaseModel):
    title: str
    platform: str = ""
    url: str = ""
    brand: str = ""
    model: str = ""
    sku: str = ""
    specs: dict[str, Any] = Field(default_factory=dict)
    price: float = 0.0
    coupon: float = 0.0
    platform_discount: float = 0.0
    member_discount: float = 0.0
    subsidy: float = 0.0
    pay_discount: float = 0.0
    shipping: float = 0.0
    gift_value: float = 0.0
    condition: str = ""
    official_store: bool = False
    return_days: int = 7
    warranty_months: int = 12
    notes: str = ""


class ShoppingProfile(BaseModel):
    budget: float = 0.0
    use_case: str = ""
    devices: list[str] = Field(default_factory=list)
    brand_preferences: list[str] = Field(default_factory=list)
    sensitivities: list[str] = Field(default_factory=list)
    acceptable_risk: str = "medium"
    existing_products: list[str] = Field(default_factory=list)


class ShoppingDecisionRequest(BaseModel):
    goal: str = ""
    products: list[ShoppingProductInput] = Field(default_factory=list)
    profile: ShoppingProfile = Field(default_factory=ShoppingProfile)
    require_human_review: bool = False


class ShoppingPriceBreakdown(BaseModel):
    page_price: float
    coupon: float
    platform_discount: float
    member_discount: float
    subsidy: float
    pay_discount: float
    shipping: float
    gift_value: float
    final_price: float


class ShoppingSameItemMatch(BaseModel):
    product_index: int
    relation: str
    confidence: float
    reasons: list[str] = Field(default_factory=list)


class ShoppingRiskReport(BaseModel):
    price_risk: str
    spec_risk: str
    store_risk: str
    after_sales_risk: str
    overall_risk: str
    reasons: list[str] = Field(default_factory=list)


class ShoppingComparisonRow(BaseModel):
    index: int
    title: str
    platform: str
    model: str
    same_item_relation: str
    same_item_confidence: float
    final_price: float
    value_score: float
    risk_level: str
    suitable_for_user: bool


class ShoppingDecisionResult(BaseModel):
    best_index: Optional[int] = None
    recommendation: str
    recommendation_reason: str
    comparison_rows: list[ShoppingComparisonRow] = Field(default_factory=list)
    price_breakdowns: list[ShoppingPriceBreakdown] = Field(default_factory=list)
    same_item_matches: list[ShoppingSameItemMatch] = Field(default_factory=list)
    risk_reports: list[ShoppingRiskReport] = Field(default_factory=list)
    report_markdown: str
    final_report: str
    summary: str
    events: list[dict[str, Any]] = Field(default_factory=list)
