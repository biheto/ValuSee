# ValuSee Browser Extension

1. Start ValuSee locally or deploy it at `https://valusee.com`.
2. Open `chrome://extensions` or `edge://extensions`.
3. Enable Developer mode and choose **Load unpacked**.
4. Select this `extension/` directory.
5. Open the extension settings, enter the ValuSee address and sign in. Administrators with MFA enabled must also enter the current authenticator code. Local development may use `http://127.0.0.1:8000` without a token.
6. Open a supported product detail page, review the visible SKU, price, discounts, region and membership conditions, then send it to ValuSee.

The extension only reads the product page the user is currently viewing. It does not crawl search results or bypass login/captcha controls. Captured fields enter a `pending_confirmation` inbox; a price snapshot is persisted only after final confirmation in ValuSee.

After updating the unpacked extension, click **Reload** on the browser extension management page. Version 0.3 can inject its collector into an already-open product tab, validates saved sessions against the API, and reports missing title, price, or SKU fields separately.
