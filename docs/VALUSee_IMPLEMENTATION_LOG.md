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
- Account security now includes single-use, expiring, SHA-256-hashed email-verification and password-reset tokens. Production sends links only by email; development may return a test token. Password-reset requests use a uniform response to prevent email-account enumeration.
- Release observability now includes bounded-cardinality Prometheus HTTP counters/durations, production token protection for `/metrics`, database/Redis/RabbitMQ/object-storage readiness, RabbitMQ queue depth, and container health checks.
- First-party product analytics accepts only an explicit event and metadata allowlist. Stable SHA-256 experiment assignment supports draft, scheduled running, paused, and completed experiments without collecting arbitrary client payloads.
- The Web release includes SEO metadata, share-specific escaped Open Graph titles, a React error boundary, skip navigation, visible keyboard focus, reduced-motion support, and semantic alert states.
- Production backup and restore scripts cover PostgreSQL, MinIO, and local attachment volumes with SHA-256 manifests. Restore requires an explicit confirmation phrase and release verification checks health, readiness, metrics authorization, and the public Web shell.
- Backups now use a versioned manifest and a non-destructive verifier for required files, sizes, SHA-256 checksums and safe tar members. Request IDs, JSON access logs, latency histograms, dependency/queue gauges and loadable Prometheus alert rules close the local observability loop.
- Administrator security now includes encrypted TOTP enrollment, MFA-bound sessions, old-session revocation and single-use recovery codes, with setup and login flows in the production admin UI.
- GitHub Actions now runs the Python suite, a correctness-focused Ruff gate, the production Web build, and Python/npm dependency audits. The broader historical style backlog is deliberately not misrepresented as a release failure.

### Product search and operations console

- Added `POST /api/v1/shopping/search`: configured official/affiliate adapters return source-bearing product records with platform, price/spec fields, and validated original URLs; no configured provider produces an explicit empty state instead of invented listings.
- Added a user-facing real-source search panel with loading, source health, empty state, direct product links, and add-to-comparison actions.
- Added `/admin` as a separate ValuSee Admin Console with protected overview, Agent task list, LLM Trace usage, commerce-source status, MCP status, and refresh controls.
- Production admin access requires `VALUSee_ADMIN_EMAILS`; development keeps a local preview for verification.
- Admin Agent task rows now support detail drill-down into persisted task payloads/artifacts for operational debugging and review.
- Added protected monitor operations for administrators: pause, resume, retry, expire, and delete. Each action validates the monitor state transition and writes an immutable action record with actor, reason, previous status, next status, and timestamp. This gives operations a recovery path when a commerce source or scheduled check fails.
- Added an admin-owned canonical commerce catalog with product and SKU CRUD. Product records store normalized brand/model/category/specifications; SKU records store variants, source URLs, and status so matching can be corrected without changing raw marketplace observations.
- Added provider health checks that call the configured adapter's authenticated `/health` endpoint and return only status/error type, never credentials. Added protected admin endpoints for prompt version listing/saving/activation and benchmark run listing.
- Added an interactive Business Governance tab to `/admin`: operators can create/delete canonical products, inspect SKU counts, publish and activate Prompt versions, pause/resume/retry price monitors, and inspect Benchmark runs without calling APIs manually.
- Business Governance now supports creating/deleting concrete SKU variants under a canonical product and launching MCP, LLM, RAG, Workflow, or Collaboration benchmarks from the console. Runs are persisted and immediately appear in the results list.
- The default RAG release benchmark now seeds an isolated, deterministic fixture collection when no managed Gold Set exists. A clean installation therefore tests actual ingest/retrieval behavior instead of failing because user knowledge has not been created yet; configured Gold Sets still take precedence.
- Added explicit JD, Taobao/Tmall, and Pinduoduo authorization slots in both the consumer search area and admin source view. They remain visibly pending until a real provider is configured and never fall back to invented listings.

### Consumer decision workbench

- Four consumer views: product analysis, price monitoring, purchases, and report history.
- Multi-product editing with platform, brand, model, price, coupon, platform discount, and official-store fields.
- Deterministic landed-price calculation, SKU relation output, risk levels, personal-fit recommendation, and Markdown decision report.
- Persisted price monitor records and purchase after-sales deadlines in SQLite.
- Product URL parsing at `POST /api/v1/shopping/parse-url`. The parser identifies common platform domains and returns an editable draft. It deliberately does not invent price or SKU facts.
- Local report restoration after page refresh.
- Consumer UI no longer exposes internal Agent execution terminology in the primary journey. The decision timeline is presented as buyer-facing evidence checks, technical controls remain under `/admin`, and the default comparison list no longer loads `example.com` demo listings or implied prices.
- Product details now use stable owner-scoped `/product/{product_ref}` routes backed by normalized records from favorites, recent views, comparisons, reports, monitors, and purchases. A refreshed URL restores the same user-owned product instead of relying on transient drawer state.
- Product detail aggregates only persisted evidence: extension/user price snapshots render as a trend line, same-SKU source offers remain separate from alternate SKUs, and source-bearing review defect evidence includes sample size and confidence. Missing evidence remains an explicit empty state.
- The comparison workbench supports drag and keyboard-friendly button ordering, difference-only specification views, collapsible dimensions, revocable share links, PNG snapshots, and print/PDF output with source-freshness warnings.
- Favorites and history now support account-scoped groups, search, selection, bulk move/delete, and an explicit unfollow action for brands. Bulk operations cap requests at 100 records and silently exclude records owned by another account.
- The message center groups price, after-sales, and system events; supports unread filtering, detail navigation, selection, bulk read/delete, individual deletion, and delivery retry. Every channel attempt is persisted with attempt number, result, and status while the in-app message remains canonical.
- Account export and deletion include product records, review evidence, saved groups, group memberships, and notification delivery attempts, keeping the new retention features inside the privacy lifecycle.
- Discovery content now has public search, complete category filtering, stable `/content/{content_id}` pages, related guides/topics, source links, and escaped per-page SEO metadata. Consumer reads are restricted to published content; guessed draft, reviewing, and offline IDs return 404.
- Content bodies render as text paragraphs rather than trusted operator HTML, and governed source URLs accept only HTTP(S), preventing stored script markup or script-protocol links from entering the consumer page.
- Family membership now uses seven-day pending invitations that only the matching registered account can accept or decline. Guessing an invitation ID, accepting from another account, reusing a response, or accepting after expiry is rejected.
- Family workspaces include shared item/device records and monthly/annual budgets. Members are read-only, editors can maintain assets and budgets, and only owners can invite, promote, demote, or remove members.
- Family assets, budgets, and relevant invitations are included in account export. Deleting a family owner removes the owned workspace records; deleting a member removes only that account's membership/invitations and does not erase shared family data.
- The account center now supports display name, short bio, locale, default currency, private avatar upload, real binding status, and user-visible audit history. Avatar uploads are limited to 2MB JPEG/PNG/WebP with MIME signatures verified before storage; SVG/HTML and mismatched files are rejected.
- Private avatars are fetched with the user's bearer session and rendered through a temporary browser Blob URL. Replacing or deleting an account removes the prior local/S3 object, while account exports include profile and audit records without exposing password/session token hashes.
- The savings center now persists monitor groups and delivery cadence, named budget pools, a 90-day source-observation calendar, and an immutable savings ledger. Monitor preferences remain owner-scoped and are removed with the monitor.
- Savings entries are generated from identifiable purchase/price-protection/coupon sources and are unique per source record. A lower paid price can create a purchase savings entry once; the client cannot directly overwrite the cumulative savings total.
- Savings ledger, budget pools, and monitor preferences are included in account export/deletion. Price-calendar cells aggregate only the account's persisted source snapshots and stay empty when no traceable observations exist.

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

## Latest product iteration

- Server-backed user profile, comparison list, decision report history, notification preferences, monitor editing, and correction feedback are now part of the consumer workflow.
- Admin feedback review and business outcome metrics close the loop between user corrections and product quality: completion, acceptance, monitor conversion, resolution, savings, and P95 latency.
- PWA manifest, responsive install icons, and a private-data-safe offline shell are included in the release build.
- Consumer information architecture now includes Discover, Smart Comparison, Savings, Orders/After-sales, Favorites/History, Messages, Account, Product Details, Family, Preferences, and account-backed reports.
- Favorites, recent views, followed brands, message read state, dashboard totals, and purchase lifecycle changes are persisted and owner-scoped; account export/deletion includes the new engagement records.
- Buying guides/topics use a governed draft/review/published/offline lifecycle. Only published records appear on the consumer home page, and optional source URLs remain visible.
- Mobile navigation, responsive product cards, explicit empty/error states, and a source-aware product-detail drawer complete the first consumer UX pass.
- Savings and after-sales now form an auditable loop: monitor groups/frequencies, budget pools, a deduplicated savings ledger, 90-day price calendar, typed private attachments, user-reported price-protection outcomes, and authenticated iCalendar deadline export.
- Membership has enforceable quotas plus owner-scoped billing orders and immutable price snapshots. Until an approved payment provider is configured, orders remain `pending_external_payment` and never activate Pro or claim a successful charge.
- Customer support now tracks a 24-hour SLA, first response, assignment, closure/reopen state, and 1-5 satisfaction feedback; customer and administrator permissions are enforced separately.
- Product records now retain immutable change versions with source confidence. Price observations need a three-point baseline before extreme deviations are queued for administrator review and audit instead of silently contaminating trusted history.
- Account dashboard KPI cards now navigate to savings, reports, favorites, and purchases with mouse and keyboard support. Account-related destination pages expose a consistent back action, and browser history now clears product/content overlays correctly on `popstate`.
- The production Compose stack now runs end to end locally: PostgreSQL/pgvector, Redis, RabbitMQ, MinIO, the API, and the independent monitor worker pass readiness checks and retain data across a full stop/start. A one-shot bucket initializer and API-proxied private downloads keep object storage internal.
- Administrators can disable MFA with a current TOTP/recovery code or, from an already MFA-verified session, by re-entering the account password. Invalid passwords leave MFA enabled and the fallback does not weaken admin login enforcement.

| Area | Status | Notes |
| --- | --- | --- |
| Consumer analysis UI | MVP complete | Web workbench is buildable and uses the shopping APIs. |
| URL input | MVP complete | User-supplied URL parsing; price/spec confirmation remains explicit. |
| Screenshot OCR | MVP complete | Secure upload, SHA-256, MIME/size validation, optional Tesseract adapter, explicit fallback, and editable product draft are implemented. |
| Product understanding model | MVP complete | OCR text normalization extracts title, known brand, model token, visible price, category hints, and an editable candidate requiring confirmation when evidence is weak. |
| Browser extension | MVP complete | Load-unpacked Manifest V3 package reads user-visible fields on supported product pages and writes a confirmation inbox. |
| Authorized commerce APIs | Adapter-ready | Provider boundary and configuration are documented; live JD/Taobao/affiliate credentials and approval are external release prerequisites. |
| Price monitor scheduler | MVP complete | Independent restart-safe worker consumes new price snapshots, deduplicates checks, updates monitors, and emits notifications. |
| Notifications | MVP complete | Durable idempotent in-app notifications, browser polling, configurable TLS SMTP email, and signed Webhook delivery are implemented. |
| Notification delivery | MVP complete | Account-email delivery through configurable TLS SMTP and signed Webhook delivery are implemented. Failed external delivery never removes the canonical in-app notification; SMS/mobile Push can be attached behind the signed Webhook after a provider is purchased. |
| Accounts and family isolation | MVP complete | Registration/login, PBKDF2 password hashing, signed sessions, production auth enforcement, user-scoped shopping data, and family ownership/membership tables are implemented. |
| Family collaboration | MVP complete | Consumer UI supports family creation, member listing, adding registered members, owner-controlled editor/member roles, and member removal. Server-side checks prevent members from changing roles or removing the owner. |
| Historical prices | MVP complete | Extension observations persist source, URL, time, region, membership, discount conditions, landed price, low/average price, and percentile. |
| Production storage | Locally verified | `DATABASE_URL` switches shopping and account stores to PostgreSQL; Redis rate limiting, RabbitMQ event publication, private S3/MinIO storage, bucket initialization, health checks, and persistent restart recovery passed against the production Compose stack. |
| Review risk analysis | MVP complete | Source-bearing reviews are weighted by verified purchase and rating, clustered into defect groups, and returned with evidence and confidence. |
| Observability | MVP complete | Health/readiness probes, structured Worker logs, durable task records, idempotency keys, source evidence, account-scoped business events, admin metrics, savings and feedback outcomes are present; external metrics/alerting wiring remains deployment-specific. |
| Monitor operations | MVP complete | Consumer and admin UI support stateful pause/resume/retry/target editing/delete actions with audit records and owner checks. |
| Product/SKU governance | MVP complete | Admin CRUD, normalized persistence, and the first operational UI are implemented; marketplace credentials and product ingestion remain external release prerequisites. |
| Provider diagnostics | MVP complete | Configured providers can be health-checked through a protected admin endpoint; no provider is represented as live without credentials. |
| Account continuity | MVP complete | Profile, saved comparison, report history, notification settings, feedback correction, export, and deletion flows are server-backed and account-isolated. |
| Installable client | MVP complete | Web build includes manifest, icons, install metadata, and a public-only offline shell. |
| Release automation | MVP complete | CI, dependency audits, backup/restore manifests, release smoke verification, Prometheus metrics, and controlled experiments are implemented; external alert routing and off-site backup retention are deployment configuration. |

## Next implementation order

1. Configure approved commerce providers and validate signed response adapters in staging.
2. Deploy the production Compose stack behind TLS and verify SMTP/Webhook notification channels.
3. Replace local development defaults with production secrets, domain allowlists, backups, monitoring, and alerting.
4. Populate real source-bearing historical prices/reviews through approved APIs, user observations, or extension captures.

## Verification rule

Every feature must include an automated check or a deterministic integration check, update this document, and be committed with author `biheto` before moving to the next feature.
