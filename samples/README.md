# Samples

Real newsletter `.eml` files used as offline ingestion fixtures. Committed to the repo so unit tests and the local ingestion pipeline have stable input.

## Before committing a new `.eml`

Scrub the subscriber email address. Run from inside `samples/`:

```bash
sed -i '' 's/real\.name@gmail\.com/reader@example.com/g' *.eml
sed -i '' 's/real\.name=gmail\.com/reader=example.com/g' *.eml
```

The second pass catches the URL-encoded variant that appears in unsubscribe links (`@` becomes `=`). Replace `real.name@gmail.com` with the address you actually need to scrub.

Also check for:
- Unsubscribe / preference-center links that embed the address or a subscriber-id hash as a query param.
- Any other `To:`, `Delivered-To:`, `X-Original-To:`, or `Return-Path:` headers that leak the address.

`example.com` is RFC 2606-reserved for documentation and test use, so it's safe as a stand-in.
