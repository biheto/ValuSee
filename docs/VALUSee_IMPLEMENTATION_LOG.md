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

### Productization and release hardening

- Production Compose profile includes API, monitor worker, PostgreSQL/pgvector, Redis, RabbitMQ, and MinIO with health checks and non-root/read-only runtime settings.
- `DATABASE_URL` switches account and shopping stores from local SQLite to PostgreSQL without changing business APIs.
- Redis distributed rate limiting, RabbitMQ durable price events, S3/MinIO image storage, readiness probes, security headers, and trusted-host/CORS controls are wired.
- Configurable official/affiliate commerce provider adapters and signed notification webhook delivery are available without pretending that unapproved platform credentials exist.
- Account export, account deletion, family member invitation, privacy policy, and service terms endpoints are available.
- Release and deployment acceptance criteria are recorded in `docs/VALUSee_PRODUCTION_RELEASE.md`.

### Product search and operations console

- Added `POST /api/v1/shopping/search`: configured official/affiliate adapters return source-bearing product records with platform, price/spec fields, and validated original URLs; no configured provider produces an explicit empty state instead of invented listings.
- Added a user-facing real-source search panel with loading, source health, empty state, direct product links, and add-to-comparison actions.
- Added `/admin` as a separate ValuSee Admin Console with protected overview, Agent task list, LLM Trace usage, commerce-source status, MCP status, and refresh controls.
- Production admin access requires `VALUSee_ADMIN_EMAILS`; development keeps a local preview for verification.
- Admin Agent task rows now support detail drill-down into persisted task payloads/artifacts for operational debugging and review.

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

Runtime branding no longer depends on loading the large PNG logo, wordmark, or mascot files. `web/src/BrandArt.tsx` provides reusable React/CSS `BrandMark`, `BrandWordmark`, and `ValueMascot` components that preserve the coral price-tag shape, yellow “见” glyph, mint check, sparkle, and Xiaozhi character cues. This removes broken deployment paths and keeps the artwork sharp at every rendered size; the original images remain reference and store-listing material only.

## Release status

| Area | Status | Notes |
| --- | --- | --- |
| Consumer analysis UI | MVP complete | Web workbench is buildable and uses the shopping APIs. |
| URL input | MVP complete | User-supplied URL parsing; price/spec confirmation remains explicit. |
| Screenshot OCR | MVP complete | Secure upload, SHA-256, MIME/size validation, optional Tesseract adapter, explicit fallback, and editable product draft are implemented. |
| Product understanding model | MVP complete | OCR text normalization extracts title, known brand, model token, visible price, category hints, and an editable candidate requiring confirmation when evidence is weak. |
| Browser extension | MVP complete | Load-unpacked Manifest V3 package reads user-visible fields on supported product pages and writes a confirmation inbox. |
| Authorized commerce APIs | Adapter-ready | Provider boundary and configuration are documented; live JD/Taobao/affiliate credentials and approval are external release prerequisites. |
| Price monitor scheduler | MVP complete | Independent restart-safe worker consumes new price snapshots, deduplicates checks, updates monitors, and emits notifications. |
| Notifications | MVP complete | Durable idempotent in-app notifications and browser polling are implemented; production email/push adapters remain optional integrations. |
| Accounts and family isolation | MVP complete | Registration/login, PBKDF2 password hashing, signed sessions, production auth enforcement, user-scoped shopping data, and family ownership/membership tables are implemented. |
| Historical prices | MVP complete | Extension observations persist source, URL, time, region, membership, discount conditions, landed price, low/average price, and percentile. |
| Production storage | Runtime-ready | `DATABASE_URL` switches shopping and account stores to PostgreSQL; Redis rate limiting, RabbitMQ event publication, and S3/MinIO upload storage are wired, with a production Compose profile and health checks. |
| Review risk analysis | MVP complete | Source-bearing reviews are weighted by verified purchase and rating, clustered into defect groups, and returned with evidence and confidence. |
| Observability | Foundation present | Health/readiness probes, structured Worker logs, durable task records, idempotency keys, and source evidence are present; external metrics/alerting wiring remains deployment-specific. |

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
