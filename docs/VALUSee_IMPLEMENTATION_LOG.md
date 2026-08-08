# ValuSee Implementation Log

This document records product-facing work, verification, deployment decisions, and known release gaps. It is updated with each completed feature commit.

## Product contract

ValuSee is an AI shopping decision and savings agent. Its user-facing loop is:

```text
need -> product understanding -> SKU matching -> landed price -> risk -> personal fit
-> timing -> monitoring -> price protection / returns / warranty
```

The first release focuses on digital products and small appliances. The system must explain its price inputs, ask for confirmation before external actions, preserve monitoring tasks across restarts, and avoid large-scale crawling as the primary data source.

## Completed

### Consumer decision workbench

- Four consumer views: product analysis, price monitoring, purchases, and report history.
- Multi-product editing with platform, brand, model, price, coupon, platform discount, and official-store fields.
- Deterministic landed-price calculation, SKU relation output, risk levels, personal-fit recommendation, and Markdown decision report.
- Persisted price monitor records and purchase after-sales deadlines in SQLite.
- Product URL parsing at `POST /api/v1/shopping/parse-url`. The parser identifies common platform domains and returns an editable draft. It deliberately does not invent price or SKU facts.
- Local report restoration after page refresh.

### Brand assets

Brand assets supplied by the product owner are stored under `web/public/brand/` and are reserved for:

- site and introduction artwork;
- application icon and compact brand mark;
- splash / launch artwork;
- feature selling-point panels;
- Xiaozhi character IP and promotional scenes;
- store listing and showcase images.

## Release status

| Area | Status | Notes |
| --- | --- | --- |
| Consumer analysis UI | MVP complete | Web workbench is buildable and uses the shopping APIs. |
| URL input | MVP complete | User-supplied URL parsing; price/spec confirmation remains explicit. |
| Screenshot OCR | MVP complete | Secure upload, SHA-256, MIME/size validation, optional Tesseract adapter, explicit fallback, and editable product draft are implemented. |
| Product understanding model | Partial | OCR text normalization extracts title, known brand, model token, and visible price; richer category/spec extraction remains. |
| Browser extension | MVP complete | Load-unpacked Manifest V3 package reads user-visible fields on supported product pages and writes a confirmation inbox. |
| Authorized commerce APIs | Planned | Requires platform credentials and approved data contracts. |
| Price monitor scheduler | Partial | Persistent records and manual checks exist; external scheduler/worker is pending. |
| Notifications | Partial | In-app status is modeled; email/push/browser delivery is pending. |
| Accounts and family isolation | Planned | Current MVP uses `local-user`; production identity and ACL are pending. |
| Historical prices | Partial | Price checks are persisted; a real historical time-series source is pending. |
| Production storage | Partial | SQLite is the local default; PostgreSQL/Redis/object storage/queue deployment is pending. |
| Review risk analysis | Partial | Deterministic risk checks exist; real review ingestion and evidence ranking are pending. |
| Observability | Foundation present | Runtime events and task records exist; production metrics and alerting remain. |

## Next implementation order

1. Product understanding normalization and user confirmation workflow.
2. PostgreSQL/Redis/object storage/queue compose profile and repository interfaces.
5. Durable monitor worker, retries, idempotency, and notification adapters.
6. Account, session, personal/family scopes, export, and deletion flows.
7. Historical price snapshots and price-position calculations.
8. Review evidence ingestion, retrieval, and risk summary.
9. Production hardening, security checks, deployment documentation, and release verification.

## Verification rule

Every feature must include an automated check or a deterministic integration check, update this document, and be committed with author `biheto` before moving to the next feature.
