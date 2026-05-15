# Cloudreve Worker Authentication Notes

`nexus.worker` subscribes to `GET /api/v4/file/events` with a Cloudreve bearer access token.

Preferred configuration for production-like local development is OAuth app authorization. Register a Cloudreve OAuth app and use this redirect URL:

```bash
CLOUDREVE_OAUTH_CLIENT_ID=<client-id>
CLOUDREVE_OAUTH_CLIENT_SECRET=<client-secret>
CLOUDREVE_OAUTH_REDIRECT_URI=http://localhost:8000/api/auth/cloudreve/callback
CLOUDREVE_OAUTH_SCOPE=offline_access
CLOUDREVE_TOKEN_STORE_PATH=data/runtime/cloudreve_tokens.json
```

Open `GET /api/auth/cloudreve/start` from the Nexus API, or use the web console authorization button. After Cloudreve redirects back to `/api/auth/cloudreve/callback`, Nexus exchanges the code for tokens and saves them to `CLOUDREVE_TOKEN_STORE_PATH`. `CloudreveClient` reads that token store on startup, so worker and manual ingestion can recover after an access token expires.

The web console authorization status actively calls Cloudreve's refresh endpoint before showing `authorized`. A token file that merely contains old tokens is not enough. If Cloudreve returns a refresh failure, the console should show that re-authorization is required.

Manual token configuration is still supported when OAuth app credentials are not available:

```bash
CLOUDREVE_ACCESS_TOKEN=<access-token>
CLOUDREVE_REFRESH_TOKEN=<refresh-token>
```

`CLOUDREVE_TOKEN` is still supported as a legacy alias for `CLOUDREVE_ACCESS_TOKEN`. The OAuth token store has priority over manual environment tokens.

When Cloudreve returns an authentication failure, the client calls `POST /api/v4/session/token/refresh` with `CLOUDREVE_REFRESH_TOKEN`, updates the in-memory access token, and retries the failed request once. This covers both file download requests and the SSE event stream connection.

Use a real Cloudreve API bearer access token here. Do not copy the `publicKey.challenge` value returned by `PUT /api/v4/session/authn` into `CLOUDREVE_TOKEN` or `CLOUDREVE_ACCESS_TOKEN`.

That `challenge` is only part of the WebAuthn login flow, so the worker cannot use it to authenticate the events stream. If you do, Cloudreve may answer the events request with `502 Bad Gateway` instead of opening the stream.

If the refresh token expires or is missing, the worker cannot self-heal and needs Cloudreve re-authorization.
