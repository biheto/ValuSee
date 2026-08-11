# ValuSee Monitor Cron

Cloudflare Cron Worker calls the protected ValuSee monitor endpoint every ten minutes. The
backend collector applies each monitor's own polling frequency, so products are not fetched
more often than their configured realtime, daily, or weekly schedule.

## Deploy

Use the same randomly generated secret in Vercel and Cloudflare. Never place it in this folder.

```powershell
cd cloudflare/monitor-cron
npm install
npx wrangler login
npx wrangler secret put VALUSee_CRON_SECRET
npm run deploy
```

Add `VALUSee_CRON_SECRET` as a sensitive Production environment variable on the Vercel
`valuesee-api` project, then redeploy the backend before deploying this Worker.

Test a scheduled run locally with `npm run dev`, then open
`http://localhost:8787/__scheduled` in another terminal or browser.
