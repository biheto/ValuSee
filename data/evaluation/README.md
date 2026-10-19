# ValuSee evaluation seed set

`sku_pairs_seed.jsonl` is a small, manually assembled seed set for establishing a SKU-matching evaluation workflow. It is not a measured result and is not ready to calculate accuracy: every row is marked `needs_human_review` because its product facts and relation label still need independent verification against the cited page(s).

The URLs point to public manufacturer product/support pages. Pages may change, redirect by region, or disappear. `source_checks.jsonl` records fetch status and short visible-text excerpts from the pages reachable on 2026-10-18. Nintendo's OLED page says 7-inch OLED and 64 GB; its Lite page describes a system dedicated to handheld play. PlayStation's fetched page did not establish the disc-drive distinction in `sku-005`. Sony and Canon returned HTTP 403. Apple's AirPods Pro specs page currently describes a later generation and does not substantiate the historical AirPods Pro 2 rows. Consequently all product rows remain provisional; do not treat them as source-verified. The snippets are provenance aids, not a full-page archive, and no automated extraction was used to populate the product fields.

## Annotation rules

- The unit is an anchor/candidate pair. For the product-level SKU metric, mark `same` only when the sellable configuration is the same. Per the evaluation owner's decision on 2026-10-19, any saleable configuration difference is a different SKU, including color, size, capacity, connector, flavor, pack count, region, condition, or bundle.
- Use `different_model`, `different_variant`, or `different_bundle` to describe the reason for a non-match. These all count as non-match for binary Top-1/precision/recall/F1 calculations. Use `insufficient_evidence` when the pages do not establish identity; exclude unresolved rows from scoring until adjudicated.
- Verify both product pages, capture the page title and relevant visible text/specifications, and record the actual access date. Prefer an archived snapshot or a stable official spec page. Do not infer a seller SKU from a model name.
- Have two annotators label independently, then adjudicate disagreements. Replace `needs_human_review` with `verified` only after that process. Keep source URL and evidence with every record.

## Fields

- `pair_id`: stable unique sample identifier.
- `anchor`, `candidate`: product observations using ValuSee's title/brand/model/SKU/specs fields plus a source URL.
- `gold_relation`: intended relation label; treat as provisional until reviewed.
- `gold_label_status`: must be `verified` before inclusion in reported evaluation metrics.
- `evidence_note`: annotation rationale and known caveats, not extracted page text.

This initial file contains 12 pairs, not 100-300 independent labeled groups. Expand it with observed listing text from multiple platforms, hard negatives, and a held-out split before reporting SKU accuracy. OCR exact-match evaluation also needs screenshot/image examples and field-level gold transcriptions; this file is not an OCR dataset.

## Official product-page crawl

`official_products.jsonl` contains page observations fetched on 2026-10-19 from public US-English product pages at Nintendo, IKEA, Logitech, PlayStation, Apple, Nike, CeraVe, The Ordinary, and Lay's. It stores the source URL, fetch time/status, page title, product name, brief description excerpt, and any Product JSON-LD properties captured for offer, variant, and additional-property specifications. The excerpt is capped at 500 characters; full HTML is not stored. Offer prices and availability are time-sensitive page observations, not stable claims.

The current run produced 11 HTTP-200 page records across gaming consoles, furniture, audio, apparel, computer peripherals, skincare, and packaged food. Ten included Product JSON-LD; one PlayStation page was reachable but had no Product schema, so it is marked `page_only_needs_human_extraction`. The structured records contain 29 nested variant entries, mainly Nike style/color/size and Logitech color/layout variants. Product identity, category assignments, and fields still require human review before use as gold labels. In particular, the IKEA page schema contains a product name but no SKU, and Logitech/Nike variant SKUs are nested under page-level variant fields. These records are product observations, not labeled same/different pairs, and must not be counted as accuracy samples.

Several sites were not added: Levi's robots/page returned 403, Patagonia returned a routing/interstitial page, lululemon returned 403, Barilla returned 403, and a second Coca-Cola product URL was 404. The collector does not retry alternate paths to evade these restrictions.

The allowlisted, rate-limited collector is `scripts/crawl_official_products.py`. It checks each host's `robots.txt`, waits between page requests, and only fetches the explicit URLs in the script. Re-run with `python scripts/crawl_official_products.py`; this refreshes the generated JSONL and therefore changes fetch timestamps and any live offer fields.

## China e-commerce status

The requested evaluation market is China, with every saleable variant difference counted as a different SKU. The US-English observations above are not China-market evaluation samples. `china_market_access_checks.jsonl` records the platform checks made on 2026-10-19. Tmall and Pinduoduo's mobile host explicitly disallow general crawlers in their robots files. JD's search endpoint returned a verification page, and a JD item URL returned a generic JD page rather than product details; `www.jd.com/robots.txt` itself returned HTML rather than a readable robots file. Xiaomi's official site disallows `/item/` paths. No verification pages, search-engine snippets, or guessed product data were added as Chinese product records.

To continue without credentials or bypassing controls, provide 5-10 ordinary share URLs per target category/platform (JD, Tmall, Pinduoduo, or another China marketplace). For pages visible only inside an app/account, provide screenshots or an export of the product page/variant selector; do not send passwords, cookies, or session tokens. Start with clothing, beauty, and packaged food, and include examples that differ by size/color, capacity/packaging, and flavor/pack count so the annotation rule can be applied consistently.
