# Cloudreve Worker Authentication Notes

`nexus.worker` subscribes to `GET /api/v4/file/events` with the value from `CLOUDREVE_TOKEN` as a bearer token.

Use a real Cloudreve API bearer token here. Do not copy the `publicKey.challenge` value returned by `PUT /api/v4/session/authn` into `CLOUDREVE_TOKEN`.

That `challenge` is only part of the WebAuthn login flow, so the worker cannot use it to authenticate the events stream. If you do, Cloudreve may answer the events request with `502 Bad Gateway` instead of opening the stream.
