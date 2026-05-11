# wger IngredientInfo Export

Import these two files into Postman:

- `docs/postman/wger_ingredientinfo.postman_collection.json`
- `docs/postman/wger.postman_environment.json`

Select the `Pete-E wger` environment before running requests.

## Quick Path

1. Optionally set `wger_auth_header` in the environment. The upstream read-only endpoint currently works without auth, but a private instance may require it.
   - API key: `Token <your-wger-api-key>`
   - JWT: fill `wger_username` and `wger_password`, then send `Auth / Get JWT Token (Optional)`.
2. Leave `wger_language_id` as `2`.
3. Open the Collection Runner and run the `IngredientInfo` folder.
4. Start with `Reset IngredientInfo Pagination`; the runner will then repeat `Fetch IngredientInfo Page` until wger returns `next: null`.
5. Watch `wger_ingredient_count_seen`, `wger_expected_total`, and `wger_page_count` to confirm pagination.

The collection calls:

```text
GET {{wger_base_url}}/ingredientinfo/?language={{wger_language_id}}&limit={{wger_page_limit}}&offset={{wger_offset}}&ordering=id
```

The local OpenAPI spec exposes both `language` and `language__code`. This setup uses the numeric language id, so language 2 is sent as `language=2`.

## Writing a JSON File

Postman request scripts cannot write directly to a local file, and the full `language=2` ingredient set is very large. On 2026-05-11, wger reported 1,358,655 matching rows.

For the full export, use the streaming helper instead of storing the data inside Postman:

```powershell
python scripts\export_wger_ingredients.py `
  --language 2 `
  --limit 10000 `
  --output docs\postman\out\wger_ingredientinfo_language_2.json
```

For a one-page smoke test:

```powershell
python scripts\export_wger_ingredients.py `
  --language 2 `
  --limit 10 `
  --max-pages 1 `
  --output docs\postman\out\wger_ingredientinfo_language_2_sample.json
```

If you still want Newman to accumulate a small test run into an exported Postman environment, set `wger_accumulate_results=true` and `wger_max_pages` to a low number:

```powershell
New-Item -ItemType Directory -Force docs\postman\out

newman run docs\postman\wger_ingredientinfo.postman_collection.json `
  -e docs\postman\wger.postman_environment.json `
  --folder IngredientInfo `
  --env-var "wger_auth_header=Token <your-wger-api-key>" `
  --env-var "wger_accumulate_results=true" `
  --env-var "wger_max_pages=1" `
  --export-environment docs\postman\out\wger.postman_environment.out.json

powershell -ExecutionPolicy Bypass `
  -File docs\postman\export_wger_ingredients_from_environment.ps1 `
  -EnvironmentPath docs\postman\out\wger.postman_environment.out.json `
  -OutputPath docs\postman\out\wger_ingredientinfo_language_2.json
```

If you use JWT auth instead of an API key, first run `Auth / Get JWT Token (Optional)` in Postman or provide `wger_auth_header=Bearer <access-token>` to Newman.

## Useful Environment Values

- `wger_base_url`: defaults to `https://wger.de/api/v2`; this matches `WGER_BASE_URL` in the app.
- `wger_language_id`: defaults to `2`.
- `wger_page_limit`: defaults to `10000`.
- `wger_accumulate_results`: defaults to `false`; only set to `true` for small test runs.
- `wger_max_pages`: optional safety cap for Postman/Newman runs.
- `wger_ingredient_count_seen`: number of accumulated ingredients.
- `wger_expected_total`: total count reported by wger.
- `wger_page_count`: number of ingredient pages fetched.
- `wger_ingredients_json`: JSON array only when `wger_accumulate_results=true`.

Do not commit an exported Postman environment after filling credentials or tokens.
