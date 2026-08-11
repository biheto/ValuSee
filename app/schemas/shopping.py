from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class ShoppingProductInput(BaseModel):
    title: str
    category: str = "unknown"
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
    store_name: str = ""
    image_url: str = ""
    selected_variant: str = ""
    region: str = "unknown"
    membership: str = "unknown"
    observation_status: str = "requires_confirmation"
    evidence: dict[str, Any] = Field(default_factory=dict)
    notes: str = ""


class ShoppingParseUrlRequest(BaseModel):
    url: str = Field(..., min_length=8)
    title: str = ""


class ShoppingSearchRequest(BaseModel):
    query: str = Field(..., min_length=2, max_length=160)
    provider: str = ""
    category: str = ""
    limit: int = Field(default=12, ge=1, le=50)


class ShoppingParseUrlResponse(BaseModel):
    product: ShoppingProductInput
    source: str
    message: str
    fetch_status: str = "not_attempted"
    cached: bool = False
    fallback_actions: list[str] = Field(default_factory=list)


class ShoppingImageResponse(BaseModel):
    asset_id: str
    file_name: str
    content_type: str
    size: int
    sha256: str
    storage: dict[str, str] = Field(default_factory=dict)
    ocr_provider: str
    ocr_text: str
    product: ShoppingProductInput
    requires_confirmation: bool
    warning: str = ""


class ShoppingExtensionCaptureRequest(BaseModel):
    user_id: str = "local-user"
    product: ShoppingProductInput
    source: str = "browser_extension"
    captured_at: Optional[str] = None


class ShoppingExtensionCaptureResponse(BaseModel):
    capture_id: str
    user_id: str
    status: str
    product: ShoppingProductInput
    source: str
    captured_at: str
    created_at: str
    confirmed_now: bool = False


class ShoppingExtensionConfirmRequest(BaseModel):
    product: Optional[ShoppingProductInput] = None


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


class RegisterRequest(BaseModel):
    email: str = Field(..., min_length=5, max_length=254)
    password: str = Field(..., min_length=8, max_length=200)
    confirm_password: str = Field(..., min_length=8, max_length=200)
    verification_code: str = Field(..., pattern=r"^\d{6}$")
    display_name: str = Field(default="", max_length=60)


class RegistrationCodeRequest(BaseModel):
    email: str = Field(..., min_length=5, max_length=254)


class LoginRequest(BaseModel):
    email: str
    password: str
    mfa_code: str = Field(default="", max_length=32)


class PasswordResetRequest(BaseModel):
    email: str = Field(..., min_length=5, max_length=254)


class PasswordResetConfirmRequest(BaseModel):
    token: str = Field(..., min_length=20, max_length=500)
    new_password: str = Field(..., min_length=8, max_length=200)
    confirm_password: str = Field(..., min_length=8, max_length=200)


class EmailVerifyConfirmRequest(BaseModel):
    token: str = Field(..., min_length=20, max_length=500)


class FamilyCreateRequest(BaseModel):
    name: str = Field(default="我的家庭", max_length=80)


class FamilyInviteRequest(BaseModel):
    family_id: str = Field(..., min_length=4, max_length=80)
    email: str = Field(..., min_length=5, max_length=254)


class FamilyMemberRoleRequest(BaseModel):
    role: str = Field(..., pattern="^(member|editor)$")


class ProductReviewInput(BaseModel):
    rating: float = Field(default=3, ge=1, le=5)
    content: str = Field(..., min_length=1, max_length=5000)
    verified_purchase: bool = False
    source: str = Field(..., min_length=1, max_length=120)
    source_url: str = ""
    created_at: Optional[str] = None


class ReviewAnalysisRequest(BaseModel):
    product: ShoppingProductInput
    reviews: list[ProductReviewInput] = Field(default_factory=list, max_length=2000)
