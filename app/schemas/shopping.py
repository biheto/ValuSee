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


class ShoppingParseUrlRequest(BaseModel):
    url: str = Field(..., min_length=8)
    title: str = ""


class ShoppingParseUrlResponse(BaseModel):
    product: ShoppingProductInput
    source: str
    message: str


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


class PriceMonitorCreateRequest(BaseModel):
    user_id: str = "local-user"
    product: ShoppingProductInput
    target_price: float = Field(..., ge=0)
    monitor_days: int = Field(default=30, ge=1, le=365)
    notify_channel: str = "in_app"


class PriceMonitorCheckRequest(BaseModel):
    price: float = Field(..., ge=0)
    coupon: float = 0.0
    platform_discount: float = 0.0
    member_discount: float = 0.0
    subsidy: float = 0.0
    pay_discount: float = 0.0
    shipping: float = 0.0
    gift_value: float = 0.0
    stock_status: str = "in_stock"
    source: str = "manual"


class PriceMonitorResponse(BaseModel):
    monitor_id: str
    user_id: str
    status: str
    target_price: float
    current_final_price: float
    product: dict[str, Any]
    notify_channel: str
    created_at: str
    expires_at: str
    updated_at: str
    last_message: str = ""


class PriceMonitorCheckResponse(BaseModel):
    monitor: PriceMonitorResponse
    check: dict[str, Any]
    target_reached: bool
    message: str


class PurchaseCreateRequest(BaseModel):
    user_id: str = "local-user"
    product: ShoppingProductInput
    paid_price: float = Field(..., ge=0)
    platform: str = ""
    store_name: str = ""
    purchased_at: Optional[str] = None
    price_protection_days: int = Field(default=7, ge=0, le=90)
    return_days: int = Field(default=7, ge=0, le=30)
    warranty_months: int = Field(default=12, ge=0, le=120)
    consumable_cycle_days: Optional[int] = Field(default=None, ge=1, le=730)
    notes: str = ""


class PurchaseResponse(BaseModel):
    purchase_id: str
    user_id: str
    product: dict[str, Any]
    paid_price: float
    platform: str
    store_name: str
    purchased_at: str
    price_protection_deadline: Optional[str] = None
    return_deadline: Optional[str] = None
    warranty_deadline: Optional[str] = None
    consumable_reminder_at: Optional[str] = None
    status: str
    reminders: list[dict[str, Any]] = Field(default_factory=list)
    notes: str = ""
    created_at: str
    updated_at: str
