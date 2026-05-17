# Withings Measure API Inspection

Import these two files into Postman:

- `docs/postman/withings.postman_collection.json`
- `docs/postman/withings.postman_environment.json`

Select the `Pete-E Withings` environment before running requests.

## Quick Path

If your access token is valid, this is all you need:

1. Set `withings_access_token` in the environment.
2. Set `days_back` to the day you want to inspect (`0` = today, `1` = yesterday).
3. Send `Measure / Raw GetMeas - All Measures (Use This)`.
4. Open the response body to inspect the raw Withings JSON.
5. Check the environment value `unhandled_measure_types_seen` or the Postman Console for measure type IDs Pete-E does not currently decode.

That request intentionally omits `meastypes`, so Withings can return every
measurement type recorded by the scale for that day.

## Environment Values

Copy these from your local `.env`:

- `WITHINGS_CLIENT_ID` -> `withings_client_id`
- `WITHINGS_CLIENT_SECRET` -> `withings_client_secret`
- `WITHINGS_REDIRECT_URI` -> `withings_redirect_uri`

If you already have a token file, copy these from
`/opt/myapp/shared/runtime/withings/.withings_tokens.json` when `WITHINGS_TOKEN_FILE` is configured:

- `access_token` -> `withings_access_token`
- `refresh_token` -> `withings_refresh_token`

Do not commit an exported environment after filling tokens or secrets.

## OAuth Flow

Only use this if your current access/refresh token is missing or rejected.

1. Open `OAuth / 1. Open Authorize URL In Browser (HTML Expected)`.
2. Copy the full generated URL into a normal browser. If you press Send in Postman, the HTML login page you saw is expected.
3. Log in to Withings and approve the app.
4. Copy the `code` query parameter from the final redirect URL into `withings_authorization_code`.
5. Send `OAuth / 2. Exchange Authorization Code`.
6. Postman's test script stores `withings_access_token` and `withings_refresh_token`.

If the browser redirect lands on an error or local page, that can still be fine:
look in the browser address bar for `?code=...` and copy just that value.

## Refresh Token Warning

Withings rotates refresh tokens. If you send `OAuth / 3. Refresh Access Token`,
copy the new `withings_refresh_token` back to either:

- `/opt/myapp/shared/runtime/withings/.withings_tokens.json`
- `.env` as `WITHINGS_REFRESH_TOKEN`

Otherwise the app may keep using an old refresh token.

## Useful Requests

- `Measure / Raw GetMeas - All Measures (Use This)` mirrors `WithingsClient._fetch_measures` without a `meastypes` filter.
- `Measure / Ping - Weight Measure` only checks whether the token can access weight data.
- `Measure / Get Body Composition Measures - Target UTC Day` filters to the measure types decoded by `WithingsClient.get_summary`.

Set `days_back` in the environment to choose the target UTC day. The collection
pre-request script fills `target_start_unix`, `target_end_unix`, and
`one_day_ago_unix` automatically.

## References

- Withings authorization URL docs: https://developer.withings.com/developer-guide/v3/integration-guide/public-health-data-api/get-access/oauth-authorization-url/
- Withings access/refresh token docs: https://developer.withings.com/developer-guide/v3/integration-guide/advanced-research-api/get-access/access-and-refresh-tokens/
- Withings public Postman `Measure - Getmeas` example: https://www.postman.com/withings/withings-health-solutions/request/klbwa2i/measure-getmeas
