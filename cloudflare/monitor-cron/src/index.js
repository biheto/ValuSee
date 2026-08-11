const SIGNED_PATH = "/api/v1/internal/monitor/run";

export async function sign(secret, timestamp) {
  const encoder = new TextEncoder();
  const key = await crypto.subtle.importKey(
    "raw",
    encoder.encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const message = `${timestamp}\nPOST\n${SIGNED_PATH}`;
  const signature = await crypto.subtle.sign("HMAC", key, encoder.encode(message));
  return [...new Uint8Array(signature)].map((byte) => byte.toString(16).padStart(2, "0")).join("");
}

export async function runMonitor(env) {
  if (!env.VALUSee_CRON_SECRET) {
    throw new Error("VALUSee_CRON_SECRET is not configured");
  }
  const timestamp = Math.floor(Date.now() / 1000).toString();
  const signature = await sign(env.VALUSee_CRON_SECRET, timestamp);
  const apiOrigin = (env.API_ORIGIN || "https://api.valusee.com").replace(/\/$/, "");
  const response = await fetch(`${apiOrigin}${SIGNED_PATH}`, {
    method: "POST",
    headers: {
      "X-ValuSee-Timestamp": timestamp,
      "X-ValuSee-Signature": signature,
      "User-Agent": "ValuSee-Monitor-Cron/1.0",
    },
  });
  const body = await response.text();
  if (!response.ok) {
    throw new Error(`monitor API returned ${response.status}: ${body.slice(0, 500)}`);
  }
  console.log(JSON.stringify({ event: "monitor_cycle", status: response.status, body: body.slice(0, 1000) }));
}

export default {
  async scheduled(_controller, env, ctx) {
    ctx.waitUntil(runMonitor(env));
  },
  async fetch(request, env) {
    if (new URL(request.url).pathname !== "/health") {
      return new Response("Not found", { status: 404 });
    }
    return Response.json({ status: "ok", service: "valuesee-monitor-cron", configured: Boolean(env.VALUSee_CRON_SECRET) });
  },
};
