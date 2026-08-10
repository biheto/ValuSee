# ValuSee Production Release

## What Is Shipped

ValuSee is a consumer shopping decision product for digital products and small appliances:

```text
need or link or screenshot -> OCR/product normalization -> SKU/spec comparison
-> landed-price calculation -> evidence-based risk -> personal-fit report
-> price history/target monitor -> purchase, price-protection, return and warranty reminders
```

The Web workbench and Manifest V3 browser extension are included. The extension reads only fields visible on the page the user has opened and sends a pending confirmation record to ValuSee.
The Web client is also installable as a PWA. Its offline shell contains no private API responses; account data, reports, comparisons, and notifications always come from authenticated requests.

## Production Components

- FastAPI API serves the built Web application and `/api/v1` endpoints.
- `monitor-worker` is an independent restart-safe process. It polls durable snapshots and accepts RabbitMQ price events as an acceleration path; the database scan remains the recovery path.
- PostgreSQL is selected with `DATABASE_URL` for account, shopping, monitor, purchase, notification, and snapshot records.
- A private `application-data` volume keeps compatibility state used by the legacy Harness, Skill, Benchmark, and marketplace modules while the container root filesystem remains read-only. Consumer account and shopping records continue to use PostgreSQL.
- Redis provides distributed rate-limit buckets when `REDIS_URL` is set.
- RabbitMQ publishes confirmed durable price snapshot events when `RABBITMQ_URL` is set. The worker uses a main queue, delayed retry queue and dead-letter queue; duplicate delivery remains safe because snapshot checks and notifications are idempotent.
- MinIO/S3 stores uploaded product images when `S3_ENDPOINT_URL` is set. Local development keeps a non-public ignored upload directory.
- The one-shot `object-storage-init` service creates the configured private bucket idempotently before the API starts; permission failures stop deployment instead of being hidden as missing buckets.
- Authenticated avatar and purchase-attachment downloads are streamed through the API, so the private object-storage hostname and port are never exposed to browsers.
- `/health` is a liveness probe. `/ready` checks the configured database and infrastructure dependencies.
- The monitor worker writes a cycle heartbeat. Its container health check fails when the worker remains alive but stops completing queue/scan cycles.
- `/api/v1/admin/metrics` exposes business outcomes for the latest reporting window: analysis completion, recommendation acceptance, monitor conversion, feedback resolution, estimated savings, and analysis P95 latency.
- `/metrics` exposes bounded-cardinality Prometheus HTTP counters and duration aggregates. Production requires `X-Metrics-Token` matching `VALUSee_METRICS_TOKEN`; do not expose this endpoint anonymously.
- Every response has a validated/generated `X-Request-ID`; JSON request logs contain route, status and latency but omit query strings, credentials and client IP addresses. Prometheus latency histograms support P95 alerts. Dependency and RabbitMQ ready/retry/dead-letter gauges are included.
- Load `ops/prometheus-alerts.yml` into Prometheus and route critical alerts to an actual on-call receiver before launch.
- First-party experiments use deterministic account assignment and an allowlisted analytics payload. Experiment creation and status changes remain administrator-only.

## Start For Release

1. Copy `.env.production.example` to `.env.production` and replace every placeholder with generated secrets and the real domain.
2. Set `ALLOWED_HOSTS` and `ALLOWED_ORIGINS` to the production host only.
3. Run `docker compose --env-file .env.production -f docker-compose.production.yml up -d --build`.
4. Put TLS termination and a request body limit in front of the API. Expose only the API/reverse-proxy port; do not expose PostgreSQL, Redis, RabbitMQ, or MinIO publicly.
   Set `FORWARDED_ALLOW_IPS` to the exact reverse-proxy addresses; wildcard proxy trust is intentionally disabled.
5. Verify `/health`, `/ready`, registration/login, screenshot upload, a price snapshot, a monitor cycle, and account export/deletion in staging before switching DNS.
6. Run `scripts/verify-release.ps1` against the TLS origin. Schedule `scripts/backup-production.ps1`, copy encrypted backups off host, and perform a quarterly restore drill with `scripts/restore-production.ps1` in an isolated environment.
   Run `scripts/restore-production.ps1 -BackupDirectory <path> -VerifyOnly` daily to verify checksums and archive safety without modifying production.

## Vercel Web Deployment

The `valu-see` Vercel project is connected to `github.com/biheto/ValuSee` with `web/` as its Root Directory. Pushes to `main` create production deployments; pull requests and other branches create isolated previews. Vercel serves only the Vite Web/PWA build. FastAPI, the monitor worker, PostgreSQL, Redis, RabbitMQ and object storage remain on the long-running Docker host.

An optional `valuesee-api` Vercel project can use `api/index.py` for lightweight preview/API validation. It is not a replacement for the Docker backend: Vercel functions have no durable local filesystem and do not run the monitor worker. Do not place production `DATABASE_URL`, queue, or object-storage state on SQLite or `/tmp`.

Set `VITE_API_BASE_URL` in the Vercel Production and Preview environments to the public HTTPS API origin, for example `https://api.valusee.com`. On the API host, add every deployed Web origin that should be trusted to `ALLOWED_ORIGINS`; keep `ALLOWED_HOSTS` scoped to the API hostname. Never point the Vercel build at `127.0.0.1` or a private address.

Local development leaves `VITE_API_BASE_URL` empty and continues to use the Vite `/api` proxy. Vercel project identifiers and OIDC credentials live under ignored `.vercel/` and `.env.local` files and must not be committed.

## External Credentials Required

The free invitation release can launch without JD/Taobao/Pinduoduo credentials. In that mode, the consumer acquisition path is user-submitted URLs, bounded public-page parsing, editable browser capture, screenshot OCR, and manual confirmation. Whole-platform search and affiliate link generation remain unavailable, and the UI states that boundary explicitly.

### LLM configuration

The production image includes the OpenAI-compatible LangChain adapter. Set `OPENAI_API_KEY`, optionally set `OPENAI_BASE_URL` for a compatible gateway, and select the default model with `DEV_AGENT_LLM_MODEL`. Per-Agent overrides and embedding settings are listed in `.env.production.example`. An empty key intentionally keeps deterministic fallback mode; startup and non-LLM workflows remain available.

After changing model configuration, recreate the API and worker containers and verify the provider inside the container without printing the secret:

```powershell
docker compose --env-file .env.production -f docker-compose.production.yml up -d --build
docker compose --env-file .env.production -f docker-compose.production.yml exec -T api python -c "from app.providers.llm_provider import llm_provider; s=llm_provider.status(); print({'enabled':s['enabled'],'model':s['model'],'source':s['source']})"
```

The platform adapter boundary is implemented at `app/shopping/providers.py`. Real JD/Taobao/affiliate use requires an approved provider contract and credentials. All credential placeholders and the `VALUSee_COMMERCE_PROVIDERS` JSON registry are consolidated in `.env.production.example`; ValuSee does not claim to provide live platform data without those credentials.

JD/Taobao/Pinduoduo `App Secret`/`Client Secret` values are not directly interchangeable with the unified adapter token: each platform still needs a signed adapter that maps its official response into ValuSee's product schema. The application intentionally returns an empty source state until that adapter and authorization are both available.

The user search panel and `/admin` console are usable without changing the consumer workflow. Search results are intentionally empty until an approved provider is configured or a user supplies a product URL/extension capture; this is a data-integrity boundary, not a placeholder catalog.

The optional `VALUSee_NOTIFICATION_WEBHOOK_URL` delivers signed server-to-server notifications. In-app notifications are always the canonical durable record. No automatic checkout, payment, refund, or external customer-service action is enabled.

## Security And Data Controls

- Production requires a non-default `VALUSee_JWT_SECRET` and bearer authentication for user data.
- Production startup fails on weak JWT/metrics secrets, wildcard hosts/origins, a non-HTTPS public URL, or a missing administrator allowlist.
- Administrators can bind TOTP MFA in the account-security tab. Enabling MFA revokes old sessions; subsequent admin logins require a dynamic code or single-use recovery code. TOTP secrets are encrypted with the independently rotatable `VALUSee_MFA_ENCRYPTION_KEY`.
- Marketplace preview/install/uninstall is administrator-only. Production rejects local package paths, non-GitHub remote hosts, private network targets, unsafe redirects, oversized downloads and archive path traversal.
- Passwords use PBKDF2-HMAC-SHA256 with per-user salts.
- User IDs are derived from the verified token; request-body `user_id` values cannot cross account boundaries.
- Uploads are type/size/hash validated and assigned random names. Production storage should use a private bucket and lifecycle policy.
- API rate limits use Redis in production and fail closed when Redis is configured but unavailable.
- Responses include nosniff, frame, referrer, permissions, and CSP headers.
- Account data can be exported through `GET /api/v1/auth/export` and deleted through `DELETE /api/v1/auth/account`.
- Saved comparison lists, decision reports, shopping profiles, notification preferences, feedback, and business events are included in export/deletion boundaries.

## Release Boundaries

The system intentionally does not invent prices, reviews, SKU matches, or discount eligibility. A screenshot/OCR result with weak evidence requires user confirmation. Price prediction is advisory and displays its evidence. Live price freshness depends on user-provided observations, browser extension data, or authorized provider APIs.

## Verification Record

- Python `compileall`: passed.
- Product normalization and evidence-based review-risk assertions: passed.
- Web `npm run build`: passed.
- Production Compose configuration validation: passed.
- Account email verification and single-use password reset: passed.
- Family owner/member authorization and role management: passed.
- Canonical product/SKU create-query-delete flow: passed.
- Admin-triggered RAG release benchmark: completed with 100% success rate on the isolated clean-install fixture.
- Local `/health`, `/ready`, consumer Web, and `/admin` smoke checks: passed on port 8200.
- API release acceptance with a temporary account passed profile save, comparison persistence, decision report persistence, monitor edit/pause/delete, feedback lifecycle, account deletion, health, and Web response checks.
- Consumer expansion acceptance passed favorite/recent persistence, dashboard aggregation, purchase status changes, governed content publication/visibility, frontend response, and test-data cleanup.
- PWA production build passed with manifest, generated icons, and public-only Service Worker cache rules.
- Automated release quality passed with 101 Python tests, the production Vite build, desktop/mobile Playwright consumer journeys (including link, extension-download, and screenshot acquisition paths), the correctness Ruff gate, production Compose parsing, and PowerShell backup/restore/release script parsing. Dependency audits remain enforced by GitHub Actions; the local npm mirror used for this verification does not implement the npm audit endpoint.
- The full production Compose stack was deployed locally with healthy API, monitor worker, PostgreSQL/pgvector, Redis, RabbitMQ and MinIO services. Application readiness, private object upload/download, account lifecycle, queue checks, and persistent database recovery after a complete Compose stop/start all passed.
- The running production image served a validated Manifest V3 extension archive. Public-page monitor observations remain pending until user confirmation; blocked, login-only, or personalized prices trigger an extension recapture reminder instead of entering trusted history.
- The installed environment does not include `pytest`; run the repository suite in CI with `pip install .[dev]`.

See `docs/VALUSee_IMPLEMENTATION_LOG.md` for the feature-by-feature history and commit record.
