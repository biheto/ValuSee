# ValuSee Production Release

## What Is Shipped

ValuSee is a consumer shopping decision product for digital products and small appliances:

```text
need or link or screenshot -> OCR/product normalization -> SKU/spec comparison
-> landed-price calculation -> evidence-based risk -> personal-fit report
-> price history/target monitor -> purchase, price-protection, return and warranty reminders
```

The Web workbench and Manifest V3 browser extension are included. The extension reads only fields visible on the page the user has opened and sends a pending confirmation record to ValuSee.

## Production Components

- FastAPI API serves the built Web application and `/api/v1` endpoints.
- `monitor-worker` is an independent restart-safe process. It polls durable snapshots and accepts RabbitMQ price events as an acceleration path; the database scan remains the recovery path.
- PostgreSQL is selected with `DATABASE_URL` for account, shopping, monitor, purchase, notification, and snapshot records.
- Redis provides distributed rate-limit buckets when `REDIS_URL` is set.
- RabbitMQ publishes durable price snapshot events when `RABBITMQ_URL` is set.
- MinIO/S3 stores uploaded product images when `S3_ENDPOINT_URL` is set. Local development keeps a non-public ignored upload directory.
- `/health` is a liveness probe. `/ready` checks the configured database and infrastructure dependencies.

## Start For Release

1. Copy `.env.production.example` to `.env.production` and replace every placeholder with generated secrets and the real domain.
2. Set `ALLOWED_HOSTS` and `ALLOWED_ORIGINS` to the production host only.
3. Run `docker compose --env-file .env.production -f docker-compose.production.yml up -d --build`.
4. Put TLS termination and a request body limit in front of the API. Expose only the API/reverse-proxy port; do not expose PostgreSQL, Redis, RabbitMQ, or MinIO publicly.
5. Verify `/health`, `/ready`, registration/login, screenshot upload, a price snapshot, a monitor cycle, and account export/deletion in staging before switching DNS.

## External Credentials Required

The platform adapter boundary is implemented at `app/shopping/providers.py`. Real JD/Taobao/affiliate use requires an approved provider contract and credentials. Configure authorized providers with `VALUSee_COMMERCE_PROVIDERS` as a JSON array; ValuSee does not claim to provide live platform data without those credentials.

Use `.env.commerce.example` as the private credential checklist. JD/Taobao/Pinduoduo `App Secret`/`Client Secret` values are not directly interchangeable with the unified `token` field: each platform still needs a signed adapter that maps its official response into ValuSee's product schema. The application intentionally returns an empty source state until that adapter and authorization are both available.

The user search panel and `/admin` console are usable without changing the consumer workflow. Search results are intentionally empty until an approved provider is configured or a user supplies a product URL/extension capture; this is a data-integrity boundary, not a placeholder catalog.

The optional `VALUSee_NOTIFICATION_WEBHOOK_URL` delivers signed server-to-server notifications. In-app notifications are always the canonical durable record. No automatic checkout, payment, refund, or external customer-service action is enabled.

## Security And Data Controls

- Production requires a non-default `VALUSee_JWT_SECRET` and bearer authentication for user data.
- Passwords use PBKDF2-HMAC-SHA256 with per-user salts.
- User IDs are derived from the verified token; request-body `user_id` values cannot cross account boundaries.
- Uploads are type/size/hash validated and assigned random names. Production storage should use a private bucket and lifecycle policy.
- API rate limits use Redis in production and fail closed when Redis is configured but unavailable.
- Responses include nosniff, frame, referrer, permissions, and CSP headers.
- Account data can be exported through `GET /api/v1/auth/export` and deleted through `DELETE /api/v1/auth/account`.

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
- The installed environment does not include `pytest`; run the repository suite in CI with `pip install .[dev]`.

See `docs/VALUSee_IMPLEMENTATION_LOG.md` for the feature-by-feature history and commit record.
