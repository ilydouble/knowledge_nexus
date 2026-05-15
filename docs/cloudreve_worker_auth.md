# Cloudreve Worker Authentication Notes

`nexus.worker` subscribes to `GET /api/v4/file/events` with a Cloudreve bearer access token.

Preferred configuration:

```bash
CLOUDREVE_ACCESS_TOKEN=<access-token>
CLOUDREVE_REFRESH_TOKEN=<refresh-token>
```

`CLOUDREVE_TOKEN` is still supported as a legacy alias for `CLOUDREVE_ACCESS_TOKEN`.

When Cloudreve returns an authentication failure, the client calls `POST /api/v4/session/token/refresh` with `CLOUDREVE_REFRESH_TOKEN`, updates the in-memory access token, and retries the failed request once. This covers both file download requests and the SSE event stream connection.

Use a real Cloudreve API bearer access token here. Do not copy the `publicKey.challenge` value returned by `PUT /api/v4/session/authn` into `CLOUDREVE_TOKEN` or `CLOUDREVE_ACCESS_TOKEN`.

That `challenge` is only part of the WebAuthn login flow, so the worker cannot use it to authenticate the events stream. If you do, Cloudreve may answer the events request with `502 Bad Gateway` instead of opening the stream.

If the refresh token expires or is missing, the worker cannot self-heal and needs Cloudreve re-authorization.
