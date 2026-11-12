# Connector authentication (Wave 0C auth spike)

Date: 2026-11-11. Stream 0C of `docs/superpowers/plans/2026-11-11-agentic-spaces-roadmap.md`.

This document records how Interspace signs in to Notion, GitHub, Google Drive/Docs and Zotero at no extra cost, and how it stores their credentials in the macOS Keychain. It feeds the provisional auth fields of the 0A Connector API and the Wave 1 connector streams (1A–1D).

## Scope of this spike and what was not done

- **Live sign-ins: none.** On 2026-11-11 the user declined all live sign-in tests for now ("None now"). Every app fact below comes from official documentation, not from a real account. Each Wave 1 connector must repeat its first real sign-in with the user present and approving that specific app.
- **Google OAuth client:** the user will create one **later**. No Google sign-in was attempted. Wave 1C builds against fakes until the client exists.
- **Keychain:** a standalone Swift prototype ran against the login keychain with a dummy value only (see [Keychain spike results](#keychain-spike-results)). No real token was stored, printed or committed.
- All sources were checked on **2026-11-11**. "Verified" means an official vendor page states the fact. "Unverified" means it is inferred or only a third-party source claims it; the source is named.

## Summary: recommended route per app

| App | Recommended route (v1) | Cost | Token lifetime | One-time user setup |
| --- | --- | --- | --- | --- |
| **Notion** | REST API (`api.notion.com`) with an **internal connection token**. Personal access token (PAT) as the alternative. Hosted MCP later, as an optional agent route only. | Free on Free plan; 180 requests/min per connection | Internal token: no stated expiry. PAT: 7 days to 1 year. | Create an internal connection, grant capabilities, share the chosen pages with it, paste the token into Interspace. |
| **GitHub** | **Fine-grained personal access token**. A user-registered GitHub App with device flow is the upgrade path. | Free; 5,000 REST requests/hour per user, shared by all of the user's tokens | 1–366 days or no expiry (org policy may cap) | Generate a fine-grained token with selected repositories and permissions, paste it into Interspace. |
| **Google Drive/Docs** | OAuth for desktop apps: PKCE (S256) and a `127.0.0.1` loopback redirect, with a **Desktop OAuth client in the user's own Cloud project**. Scope `drive.file` (+ `openid email`). | Free for standard use | Access token: read `expires_in`. Refresh token: 7 days while the app is in Testing; otherwise until 6 months unused or revoked. | Create a Cloud project, enable two APIs, configure the consent screen, publish the app to "In production", create a Desktop client. |
| **Zotero** | **Local API** on `http://localhost:23119/api/` for reads, and for writes on **Zotero 10+** via a user-approved local key. Web API key as an optional fallback. | Free; local API has no rate limit | Local key: kept if the user clicks "Always Allow". Web key: no expiry until revoked. | Update to Zotero 10, enable "Allow other applications…", click "Always Allow" on first write. |

The roadmap's assumptions changed in two places:

1. **Zotero:** the local API is no longer read-only. Zotero 10 (released 2026-08-17) added local writes. The web API key is now only a fallback.
2. **Notion:** the hosted MCP is free on every plan for core tools, but its useful change-detection filters and several tools are paid-gated, and its tokens cannot call the REST API. REST with an integration token is the better base for a connector that serves both the Spaces UI and agents.

---

## Notion

### Recommended route

Use the **REST API with an internal connection token**. Sharing pages with the connection gives a natural, user-visible scope boundary that matches the roadmap's "user-set scopes". Offer a **personal access token** as the alternative when the user wants Interspace to see everything they can see without sharing pages one by one.

Defer the hosted MCP (`mcp.notion.com`). It needs OAuth with dynamic client registration, its tokens work only with MCP, and it gates last-edited search filters behind Business or Enterprise. If added later, it is an extra agent tool route, not the connector's base.

### One-time user setup

1. In Notion, open the developer portal (Settings → Connections → Develop or manage integrations) and create an **internal** connection in your workspace. Only a Workspace Owner can do this.
2. Set capabilities: Read content, Update content, Insert content; Read comments, Insert comments; User information without email.
3. Share each page or teamspace root you want Interspace to use: page ••• menu → Connections → Add connection. Child pages inherit access.
4. Copy the token once and paste it into Interspace's native secure prompt. Interspace stores it in the Keychain.

PAT alternative: create a personal access token (owners only on Free), choose an expiry (default 1 year), and paste it the same way. No page sharing is needed.

### Verified facts

- **Cost.** The API names no plan requirement. Rate limits list a tier for "all other plans" below Business, which covers Free. https://developers.notion.com/reference/request-limits.md
- **Rate limits.** 180 requests/min per connection (about 3/s) below Business; 600/min on Business and Enterprise. Data source queries have a separate limit of about 3/s. A per-workspace limit also applies, with no figure. Over the limit: 429 `rate_limited` with `Retry-After`; handle 529 the same way. Size limits: 2,000 characters of rich text, 100 array elements, 1,000 blocks and 500 KB per payload. https://developers.notion.com/reference/request-limits.md
- **Internal connection tokens.** Static token; only a Workspace Owner can create one. No expiry is stated; the token can be refreshed manually from the Configuration tab. https://developers.notion.com/guides/get-started/internal-connections
- **Personal access tokens.** Act as their creator, so pages need no sharing. Expiry options are 7, 30, 90 or 180 days or 1 year (default 1 year). On Free only owners can create them, and that setting is not configurable. "List all users" is unavailable to PATs. The token value is shown only once. https://developers.notion.com/guides/get-started/personal-access-tokens
- **Capabilities.** Content: Read, Update, Insert (any combination). Comments: Read, Insert. User info: none, without email, or with email. https://developers.notion.com/reference/capabilities.md
- **Read and write.** Search, pages, blocks, databases and data sources, comments (create, retrieve, list, update, delete). https://developers.notion.com/llms.txt
- **API version.** The latest `Notion-Version` is `2026-03-11` and the header is required. It replaces `archived` with `in_trash` and the block-append `after` with a `position` object. Version `2025-09-03` split databases into a `/v1/databases` container and `/v1/data_sources`. https://developers.notion.com/reference/versioning.md, https://developers.notion.com/reference/changes-by-version.md
- **Listing changes.**
  - `POST /v1/search` sorts by `last_edited_time`, filters by `page` or `data_source`, and is cursor-paginated. https://developers.notion.com/reference/post-search.md
  - Search is not a complete inventory: the index lags and results may shift during pagination. https://developers.notion.com/reference/search-optimizations-and-limitations.md
  - `POST /v1/data_sources/{id}/query` accepts a `last_edited_time` timestamp filter. https://developers.notion.com/reference/filter-data-source-entries.md
  - Webhooks need "a secure (SSL) and publicly available endpoint", so they do not suit a local app. https://developers.notion.com/reference/webhooks.md
- **Hosted MCP (deferred route).**
  - "Core Notion MCP works on every plan." https://developers.notion.com/guides/mcp/get-started-with-mcp
  - Paid gating: `notion-search` editor and last-edited filters, the `last_edited` sort and some other filters need Business or Enterprise; `notion-connector-search` and `notion-query-meeting-notes` need Business or higher with Notion AI; comment update/delete, resolve, reactions and suggested edits are Business or Enterprise only. https://developers.notion.com/guides/mcp/tools-search-reference.md, https://developers.notion.com/guides/mcp/tools-comments-reference.md
  - MCP bearer tokens without browser sign-in are Business or Enterprise only. https://developers.notion.com/guides/mcp/get-started-with-mcp
  - Rate limits are the REST limits, and every tool call counts. https://developers.notion.com/guides/mcp/rate-limits.md
  - Auth: Streamable HTTP at `https://mcp.notion.com/mcp`; RFC 9728 and RFC 8414 discovery; dynamic client registration (RFC 7591) including public clients (`token_endpoint_auth_method: "none"`); PKCE S256 mandatory. Persist the `client_id`, because re-registering orphans earlier grants. https://developers.notion.com/guides/mcp/build-mcp-client.md
  - Tokens: access tokens last "about eight hours" (use `expires_in`). Refresh tokens rotate on every use, at most two are valid per grant, and reusing a rotated one after the grace period revokes the whole grant. They expire 180 days after authorization or after 30 days without a refresh. "An MCP access token works only with Notion MCP." (same page)
  - Public metadata at `https://mcp.notion.com/.well-known/oauth-authorization-server` (unauthenticated GET, 2026-11-11): `registration_endpoint` `https://mcp.notion.com/register`, `code_challenge_methods_supported` `["S256"]`, `scopes_supported` `["default","ema_issuer:manage"]`, `token_endpoint_auth_methods_supported` includes `none`.
  - Client allowlisting ("Approved MCP clients only") is Enterprise only, so it does not block a personal workspace. https://www.notion.com/help/notion-mcp

### Unverified

- **Loopback redirect URIs for the hosted MCP.** The docs only say "Always use HTTPS for redirect URIs in production" and permit plain HTTP for local development. Whether `http://127.0.0.1:<port>` registers successfully needs a live DCR test.
- **Developer terms.** `https://www.notion.com/notion/developer-terms` redirected to a 404 on 2026-11-11. Only a search summary mentions recent revisions. Re-check before Wave 3 acceptance.
- **Public-integration OAuth** token lifetimes and PKCE support are not stated (not needed for the recommended route).
- Whether `last_edited_time` is rounded to the minute is not stated; poll with an overlap window.

---

## GitHub

### Recommended route

Use a **fine-grained personal access token** for v1. Nothing is registered, no client ID ships, and its permissions are the same fine-grained set a GitHub App uses. If Interspace is ever distributed, move to a **GitHub App the user registers on their own account**, with device flow or authorization code + PKCE on a `127.0.0.1` loopback. Skip OAuth Apps (broad `repo` scope) and the GitHub MCP server's OAuth (each MCP host must register its own app).

### One-time user setup

1. GitHub → Settings → Developer settings → Personal access tokens → Fine-grained tokens → Generate new token.
2. Resource owner: your user. Repository access: "Only select repositories" (recommended) or all.
3. Permissions: Metadata read (automatic); Contents, Issues and Pull requests read and write. Start read-only if you prefer, and add write later.
4. Expiry: up to 366 days, or none.
5. Paste the token into Interspace's native secure prompt. Organization repositories need a separate token per organization, and the organization may need to approve it.

### Verified facts

- **Cost.** No GitHub doc mentions a fee for fine-grained PATs; each account can create up to 50. https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens. Registering a GitHub App is free, up to 100 per account. https://docs.github.com/en/apps/creating-github-apps/registering-a-github-app/registering-a-github-app
- **Terms.** No abuse or excessive requests, and "You may not share API tokens to exceed GitHub's rate limitations". One login per person. The terms also say GitHub may offer subscription-based access for high-throughput use; they do not promise the API is free. https://docs.github.com/en/site-policy/github-terms/github-terms-of-service
- **Rate limits.**
  - REST: 5,000 requests/hour per user, **shared** across all the user's PATs, OAuth tokens and GitHub App user tokens. https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api
  - GraphQL: 5,000 points/hour. https://docs.github.com/en/graphql/overview/rate-limits-and-query-limits-for-the-graphql-api
  - Secondary limits: 100 concurrent requests; 900 REST points/min (GET 1, writes 5); about 80 content-creating requests/min and 500/hour. (REST rate-limit page)
  - A `304` to a conditional request with an `Authorization` header does not count against the primary limit. Send writes one at a time, at least 1 second apart. https://docs.github.com/en/rest/using-the-rest-api/best-practices-for-using-the-rest-api
- **Fine-grained permissions.** Contents (files, commits; writes to contents, refs, releases; **merging a PR needs Contents write**), Issues, Pull requests, Metadata (read-only). https://docs.github.com/en/rest/authentication/permissions-required-for-fine-grained-personal-access-tokens
- **Fine-grained token limits.** One resource owner per token; "Only select repositories" option; organizations can require approval (token is `pending` until then). Lifetime default 30 days, 1–366 days or none, capped by org or enterprise policy. (PAT page above)
- **GitHub App user tokens.** Expire after 8 hours, with 6-month refresh tokens (setting on by default). A token has only permissions that both the app and the user hold. https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/generating-a-user-access-token-for-a-github-app
- **Device flow.** Must be enabled in the app settings (`device_flow_disabled` otherwise); needs only `client_id`. Code expiry `expires_in` 900 s by default; poll no faster than `interval`; `slow_down` adds 5 s. Native apps may use loopback redirects; GitHub prefers `127.0.0.1` over `localhost`. https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/authorizing-oauth-apps
- **Device flow caution.** GitHub calls device flow open to phishing and advises enabling it only for constrained environments; for native apps it prefers authorization code with PKCE. A public client ID can be reused by anyone. https://docs.github.com/en/apps/creating-github-apps/about-creating-github-apps/best-practices-for-creating-a-github-app
- **Listing changes.**
  - Issues and PRs: `since` (updated after), `sort=updated`, `state=all`; issue lists include PRs (check the `pull_request` key). https://docs.github.com/en/rest/issues/issues
  - Notifications: `since`, `Last-Modified`/`If-Modified-Since`, `X-Poll-Interval`. **"These endpoints only support authentication using a personal access token (classic)."** (re-checked directly 2026-11-11) https://docs.github.com/en/rest/activity/notifications
  - Events API: 30 s to 6 h latency, at most 300 events from 30 days; ETags make unchanged polls free. https://docs.github.com/en/rest/activity/events
  - Webhooks need a reachable endpoint; not practical locally.
- **GitHub MCP server.** "Available to all GitHub users regardless of plan type", but each MCP host must configure its own GitHub App or OAuth App for OAuth. https://docs.github.com/en/copilot/how-tos/provide-context/use-mcp-in-your-ide/set-up-the-github-mcp-server

### Consequence for the connector

The Notifications inbox is unavailable with fine-grained tokens and GitHub App tokens. v1 detects changes by polling issues and PRs with `since` and ETags on selected repositories. An inbox view would need an extra classic PAT with only the `notifications` scope, stored as a separate Keychain account; leave it out of v1.

### Unverified

- That fine-grained tokens get a 403 on `GET /notifications` comes from a third-party issue (github.com/bergaaberg/dovre/issues/31); it agrees with the official "classic only" sentence.
- Older GitHub blog posts and some IDE install guides list a Copilot seat as an MCP server prerequisite; the current docs say all plans.
- Nothing found states explicitly that a user may run their own GitHub App, limited to their account, from a desktop app. Nothing forbids it.

---

## Google Drive/Docs

### Recommended route

OAuth 2.0 for desktop apps, with a **Desktop client in the user's own Google Cloud project**:

- PKCE with `code_challenge_method=S256`.
- Redirect to `http://127.0.0.1:<ephemeral port>/` served by the Python backend for one request.
- Scopes: `openid email https://www.googleapis.com/auth/drive.file`. Add `https://www.googleapis.com/auth/documents` only if the user wants to edit Docs Interspace did not create or pick. Avoid `drive` and `drive.readonly` (restricted).
- Bring existing files into scope with a file picker, because `drive.file` sees only files the app created, opened or was given through a picker. Whether the Google Picker (a web component needing an API key) works inside the WebKit shell is a Wave 1C question.
- Publish the app to **In production** so refresh tokens do not die after 7 days; the owner clicks through the unverified-app warning once.

### One-time user setup (deferred: user will do this later)

1. Go to console.cloud.google.com and create a project, for example `interspace-personal`. Skip linking billing.
2. APIs & Services → Library: enable **Google Drive API** and **Google Docs API**.
3. Google Auth Platform → Branding → Get started: app name, support email, Audience **External**, contact email, accept the policy, Create.
4. Audience → Test users: add your own Google account.
5. Data Access → Add or remove scopes: add `.../auth/drive.file` (and `.../auth/documents` only if wanted).
6. Audience → **Publish app** ("In production"), to avoid 7-day refresh tokens. You will see the unverified-app warning once when you consent.
7. Clients → Create client → **Desktop app**. Copy the client ID and client secret into Interspace's native secure prompt. The desktop client secret is not treated as confidential by Google, but Interspace still stores it in the Keychain.

### Verified facts

- **Cost.** Drive: "All standard use of the Google Drive API is available at no additional cost." Google plans to charge for usage above quota "later in 2026", with a free daily threshold of 400,000,000 quota units per project. https://developers.google.com/workspace/drive/api/guides/limits. Docs API: the same model. https://developers.google.com/workspace/docs/api/limits
- **Quotas.** Drive: 1,000,000 units/min per project and 325,000 per user per project; edit methods cost 50 units. Docs: reads 3,000/min per project and 300/min per user; writes 600/min per project and 60/min per user. Over quota: 403 "User rate limit exceeded" or 429; back off exponentially. (limits pages above)
- **Billing.** The Workspace guide says you "might also need to enable billing" depending on the APIs. https://developers.google.com/workspace/guides/create-project
- **User type.** Internal needs a Cloud Organization, so a personal account uses External. https://support.google.com/cloud/answer/15549945
- **Testing status.** Up to 100 test users; refresh tokens expire after 7 days unless only name, email and profile scopes are requested. https://developers.google.com/identity/protocols/oauth2, https://support.google.com/cloud/answer/15549945
- **Verification.** Personal use (fewer than 100 users) is exempt; users click through the unverified-app warning. Apps in testing are not subject to verification. Apps using only non-sensitive scopes need no verification. https://support.google.com/cloud/answer/13464323. Unverified production apps requesting sensitive or restricted scopes are capped at 100 users for the project's lifetime. https://support.google.com/cloud/answer/15549945
- **CASA.** An annual security assessment is the last step of restricted-scope review. https://support.google.com/cloud/answer/13465431
- **Scope classes.** Non-sensitive: `drive.file`, `drive.appdata`. Sensitive: `documents`, `documents.readonly`. Restricted: `drive`, `drive.readonly`, `drive.metadata`, `drive.metadata.readonly`, `drive.activity*`. `drive.file` covers files the user opened or picked with the app and files the app created. https://developers.google.com/workspace/drive/api/guides/api-specific-auth, https://developers.google.com/workspace/docs/api/auth
- **`drive.file` is enough for Docs edits on in-scope files.** `documents.batchUpdate` accepts `documents`, `drive` or `drive.file`. https://developers.google.com/workspace/docs/api/reference/rest/v1/documents/batchUpdate. `files.export` accepts `drive.file`; exports are capped at 10 MB. https://developers.google.com/workspace/drive/api/reference/rest/v3/files/export
- **Desktop flow.** Desktop clients are public and "cannot keep secrets confidential". Use PKCE (S256 recommended; `plain` if the method is omitted). Loopback `http://127.0.0.1:port` or `http://[::1]:port` is recommended for macOS; `localhost` "may cause issues with client firewalls". Custom URI schemes and the out-of-band flow are no longer supported. Incremental authorization is not supported for installed apps, so request all scopes at once. Endpoints: `https://accounts.google.com/o/oauth2/v2/auth`, `https://oauth2.googleapis.com/token`, `https://oauth2.googleapis.com/revoke`. https://developers.google.com/identity/protocols/oauth2/native-app
- **Refresh tokens** expire when unused for 6 months, when the user revokes access, when a time-based grant ends, in Testing after 7 days, or on password change for Gmail scopes. At most 100 refresh tokens per account per client ID; the oldest is silently invalidated. https://developers.google.com/identity/protocols/oauth2
- **Read and write.** Drive `files.list/get/create/update/export`; Docs `documents.get` and `documents.batchUpdate`, which is all-or-nothing. (reference pages above)
- **Listing changes.** `changes.getStartPageToken`, then `changes.list` with `pageToken`, following `nextPageToken` and saving `newStartPageToken`. https://developers.google.com/workspace/drive/api/guides/manage-changes. `changes.watch` needs a public HTTPS address with a trusted certificate, so it is unusable locally. https://developers.google.com/workspace/drive/api/guides/push. `files.list` supports `modifiedTime > '…'`. https://developers.google.com/workspace/drive/api/guides/search-files

### Without an OAuth client

If the user never creates a client, Interspace cannot read private Drive or Docs content through Google's APIs. What remains:

- **Google Drive for desktop** sync folder: ordinary files (PDF, Markdown, Office files) are real files on disk that Interspace can read like any local folder. Google Docs, Sheets and Slides open in the browser, not as local content. https://support.google.com/drive/answer/10838124
- **Public files only** with an API key (still needs a Cloud project, but no OAuth client). https://developers.google.com/workspace/guides/create-credentials
- **Publish to the web**, which makes a Doc viewable by anyone with the link; not appropriate for private work. https://support.google.com/docs/answer/183965
- **Google Takeout** archives, as a manual snapshot. https://support.google.com/accounts/answer/3024190

So without a client, Drive becomes a read-only local folder source and Docs are out of reach. No writes are possible.

### Unverified

- Access token lifetime of 1 hour is not stated on the native-app page (its sample shows `expires_in: 3920`). Always read `expires_in`.
- Whether a project with no billing account can enable Drive and Docs APIs: the Cloud Billing docs say a billing account is needed even for free use, while the Workspace guide says billing is optional. Expected to work without billing; confirm when the user creates the project.
- `.gdoc` files in the sync folder: third-party sources say they are small JSON pointers (URL, doc ID) with no document text. No official page describes them.
- Whether CASA applies to an owner-only app keeping restricted-scope data locally: no official statement. Avoided by not using restricted scopes.
- A search summary mentioned new API quotas for projects created on or after 2026-05-01; not confirmed on an official page.

---

## Zotero

### Recommended route

- **Zotero 10 or later:** use the **local API only**, for reads and writes. It is free, has no rate limit and no storage quota for local files, and needs no cloud key. Zotero must be running.
- **Optional:** a web API key, for when Zotero is closed or for push notifications through the streaming API.
- **Zotero 7–9:** local reads plus web API writes; web writes appear locally only after Zotero syncs.
- Do not use the connector server (`/connector/*` on port 23119). It is the browser extension's save path, not a general write API.

### One-time user setup

1. Update Zotero to 10.x.
2. Zotero → Settings → Advanced: enable "Allow other applications on this computer to communicate with Zotero".
3. On Interspace's first write, Zotero shows an authorization dialog for Interspace. Click **Always Allow**. Interspace stores the returned local key in the Keychain.
4. Optional web fallback: at zotero.org/settings/keys create a key with personal library read, notes, and write (no group access); note the user ID shown on that page. Paste both into Interspace's secure prompt.

### Verified facts

- **Local API base.** `http://localhost:23119/api/users/0/…` (0 is the logged-in user) or `/groups/<id>/…`; API v3 only. Disabled → 403. Reads need no authentication. https://www.zotero.org/support/dev/web_api/v3/local_api
- **Local writes (Zotero 10+).** "In Zotero 10+, `POST`, `PUT`, `PATCH`, and `DELETE` are supported for items, collections, and saved searches." (re-checked directly 2026-11-11). Key: `POST /api/local/authorize` shows an Allow / Always Allow / Deny dialog; the key is single-use unless the user chooses Always Allow. Send it as `Zotero-API-Key`; re-authorize on 401. Keys are not scoped to a library and the user can clear them in Settings → Advanced. (same page) Release notes: https://www.zotero.org/support/dev/zotero_10_for_developers, https://www.zotero.org/blog/zotero-10/
- **`Zotero-Server-ID`.** Required on write requests, including `/api/local/authorize`; missing → 428, mismatch → 412 (drop cached state). (local API page)
- **Local limits.** No rate limiting in general; at most five dialog-showing requests per minute (429 with `Retry-After`). (local API page)
- **Local extras.** Saved searches run locally (`/searches/<key>/items`); full text read and write; file access via redirect to a `file://` URL; uploads up to 4 GB. In Zotero 10+ local versions are unrelated to web versions. (local API page)
- **Web API cost.** No API fee is stated. Storage: 300 MB free; paid plans are for storage. https://www.zotero.org/storage, https://www.zotero.org/support/terms/terms_of_service
- **Web API rate limits.** No numeric limits. Honour `Backoff` and `Retry-After` (429); at most 4 concurrent requests; 100 objects per page. https://www.zotero.org/support/dev/web_api/v3/basics
- **Web API key.** Sent as `Zotero-API-Key` or `Authorization: Bearer`. Valid "indefinitely, unless it is revoked by the user manually". `/keys/<key>` returns the user ID and privileges. (basics page) OAuth 1.0a also exists (register at zotero.org/oauth/apps; the returned `oauth_token_secret` is the API key). https://www.zotero.org/support/dev/web_api/v3/oauth
- **Web writes.** Up to 50 objects per request; `If-Unmodified-Since-Version` (412 on conflict, 428 if missing on delete); PATCH for partial updates; notes are child items. https://www.zotero.org/support/dev/web_api/v3/write_requests
- **Terms.** No API-specific clauses; no undue burden, no scrapers, no commercial use without permission. https://www.zotero.org/support/terms/terms_of_service
- **Listing changes.** `since=<version>` with `format=versions`, `Last-Modified-Version`, `If-Modified-Since-Version` → 304, `/deleted?since=`. https://www.zotero.org/support/dev/web_api/v3/syncing. Local API supports `since` with local versions; poll it. Streaming API (`wss://stream.zotero.org`) sends notifications only, keyed by a web API key. https://www.zotero.org/support/dev/web_api/v3/streaming_api
- **Connector server.** Documented for the browser extension; no stability promise for third parties. Zotero 10 rejects non-localhost `Host` headers and browser-like requests without `Zotero-Allowed-Request`. https://www.zotero.org/support/dev/client_coding/connector_http_server

### Unverified

- That the desktop app must be running is inferred (it is the server); the page does not say so outright.
- Latest version 10.0.9 dated 2026-11-10 comes from search results; the changelog was not fetched.
- Third-party sources saying "the local API is read-only" (pyzotero issues, gists) predate Zotero 10.
- Applying the ToS scraper clause to ordinary API use is an inference.
- Check the user's installed Zotero version before Wave 1D relies on local writes.

---

## Keychain bridge proposal

### Constraints from today's code

- `app/macos/main.swift` forwards **every** JSON line the backend writes on stdout to the WebView (`receive` → `deliver` → `window.interspaceReceive`). Anything secret on that channel would reach JavaScript.
- The WebView can only call methods in the native allowlist; all of them except `choose_project` go straight to the backend.
- Backend stderr is drained and discarded.
- The app is **ad-hoc signed** (`codesign --sign -` in `scripts/build-macos-app.py`), bundle ID `local.interspace.desktop`.

### Rules

1. Tokens never enter the WebView, `state.json`, the audit log, logs, stderr, events, tool arguments, tool results or model prompts.
2. Swift is the only code that calls Keychain APIs.
3. The Python backend holds a token in memory only while it makes the HTTP call, and the connector is the only code that reads it.
4. Agents use connector tools through Interspace's own MCP server; the tool runs in the backend with the token, and the agent sees only results.

### Keychain item naming

| Field | Value |
| --- | --- |
| Class | `kSecClassGenericPassword` |
| Service | `local.interspace.desktop.connector.<app>` with `<app>` ∈ `notion`, `github`, `google`, `zotero` |
| Account | Stable non-secret account ID: Notion workspace ID; GitHub login; Google `sub` or email; Zotero `local` or the web user ID |
| OAuth client (Google) | Service `local.interspace.desktop.oauth-client.google`, account `default` |
| Label | `Interspace: <App> (<account>)`, visible in Keychain Access |
| Data | UTF-8 JSON: `{"kind": "token" \| "oauth", "access_token", "refresh_token", "expires_at", "scopes", "client_id"}`. One item per connection, so a rotated refresh token and its access token are replaced in **one** `SecItemUpdate` (Notion MCP and GitHub App refresh tokens rotate; losing the new one revokes the grant). |
| Accessibility | `kSecAttrAccessibleWhenUnlockedThisDeviceOnly` |
| Synchronizable | `false` (not in iCloud Keychain) |
| Spike entries | Service prefix `local.interspace.spike.connector.<app>` only |

### Bridge messages

Add a **native channel** that never reaches the WebView. Swift intercepts any backend stdout line that has a top-level `"native"` key in `receive`, **before** `deliver`, and answers on the backend's stdin.

Backend → native (requests), native → backend (replies with the same `id`):

| `native` | Params | Reply | Notes |
| --- | --- | --- | --- |
| `secret.get` | `connector`, `account` | `{present, value?}` | The only reply that carries a secret, and it goes to stdin, never to the WebView. |
| `secret.put` | `connector`, `account`, `value` | `{stored}` | Used after an OAuth token exchange or refresh. |
| `secret.delete` | `connector`, `account` | `{deleted}` | Disconnect. |
| `secret.status` | `connector`, `account?` | `{present, modified}` | No value. |
| `secret.list` | `connector` | `{accounts: [...]}` | Account IDs only. |
| `auth.open_url` | `url` | `{opened}` | Opens the system browser with `NSWorkspace`. Swift allows only `https` URLs on `accounts.google.com`, `github.com` and `mcp.notion.com`. |

WebView → native (new allowlist entries):

| Method | Handled by | Notes |
| --- | --- | --- |
| `enter_connector_secret` | Swift | Shows a native sheet with an `NSSecureTextField` (one field for a token; two for the Google client ID and secret). Swift writes the Keychain item, then sends the backend `connector_secret_stored {connector, account?}` with **no value**. The pasted text never touches JavaScript. |
| `connect_app`, `disconnect_app`, `connector_status` | backend | Start OAuth or device flows, delete items, report status. Replies carry status only. |

Validation in Swift: `connector` must be one of the four names; `account` must match `^[A-Za-z0-9._@-]{1,128}$`; unknown `native` methods are rejected; native lines are never logged.

### OAuth flows in this design

- **Google (and Notion MCP if added):** the backend generates the PKCE verifier and `state`, binds a one-shot HTTP listener on `127.0.0.1` with an ephemeral port, sends `auth.open_url`, checks `state`, exchanges the code, then sends `secret.put`. The listener closes after one request or a timeout.
- **GitHub App device flow (future):** the backend shows the user code in the UI (short-lived, not a credential), sends `auth.open_url` for `https://github.com/login/device`, and polls at the given `interval`.
- **Token refresh:** serialized per connection in the backend; the new pair is written with one `secret.put` before the old token is discarded.

### Redaction and tests (Wave 1 requirement)

- Every connector test uses a canary token value and asserts it never appears in `state.json`, the audit log, emitted events, stderr capture, MCP tool results or prompt text.
- HTTP error handling strips `Authorization` and `Zotero-API-Key` headers, and any `key=` query parameter, before any error is recorded.
- A Swift-side test (or manual check) asserts a `native` line is never passed to `evaluateJavaScript`.

### Rejected alternative: Python calling `/usr/bin/security`

- `security add-generic-password -w <value>` puts the secret in the process arguments, visible to `ps`.
- Items created by `security` trust the `security` tool in their access list, so any local process that runs `security` can read them without a prompt (inference from Keychain ACL behaviour; not tested).
- It splits Keychain ownership between two processes.

### Keychain spike results

Prototype: `workspace-data/spikes/keychain/` (ignored by git). `SecretStore.swift` implements the `secret.*` messages above as a stdin/stdout line protocol; `drive.py` drives it with the dummy value `spike-dummy-value-not-a-token`. Build: `swiftc -O SecretStore.swift -o secret-store && codesign -f -s - secret-store`. Run 2026-11-11 on macOS (Darwin 25.6.0), Swift 6.2.4:

| Test | Result |
| --- | --- |
| Login keychain, ad-hoc signed binary: status, set, update, status, list, get, delete, get | All succeeded; value round-tripped; item gone after delete. |
| Unknown connector (`slack`), bad account (`../etc`) | Rejected with `invalid_request` and `invalid_account`. |
| Data-protection keychain (`kSecUseDataProtectionKeychain`) | `-34018` "A required entitlement isn't present." on set and delete. |
| Item written by ad-hoc binary A (CDHash `d0e91aa1…`), read by rebuilt binary B (CDHash `1accdcff…`) with UI disabled | `secret.status` (attributes) succeeded; `secret.get` (data) failed `-128` "User canceled the operation". Binary A could still read it. |

What this means:

- The **login (file-based) keychain** works for today's ad-hoc signed app.
- The **data-protection keychain** is not available without a provisioned signing identity and entitlements. Not needed for v1.
- **Every rebuild of an ad-hoc signed Interspace changes its code hash, so macOS will ask the user to allow Keychain access again** (with UI enabled this is the "Interspace wants to use your confidential information" prompt; "Always Allow" adds the new build). This is expected for a single-person dev build but annoying. Mitigation for Wave 1, not yet tested: sign builds with a stable local code-signing identity (a self-signed certificate created once in Keychain Access, or the user's free Apple Development certificate), so the designated requirement stays the same across rebuilds. Creating that certificate is a persistent change on the user's machine and needs the user's approval.
- The backend must treat a Keychain read failure (`-128`, `-25293`, `-25308`) as "needs reconnect or re-allow", never as a reason to fall back to a file.

### Spike cleanup

No spike Keychain items remain: on 2026-11-11 `security find-generic-password -s local.interspace.spike.connector.<app>` returned "not found" for `notion`, `github`, `google` and `zotero`. If a later live spike stores a token, remove it with:

```bash
security delete-generic-password -s local.interspace.spike.connector.<app> -a <account>
```

Remove the prototype files with:

```bash
rm -rf workspace-data/spikes/keychain
```

## Inputs for 0A provisional auth fields

Suggested `auth` block per connector in the Connector API:

- `auth.kind`: `token` (Notion, GitHub, Zotero web), `oauth_pkce_loopback` (Google; Notion MCP later), `local_key` (Zotero local), `device_flow` (GitHub App later).
- `auth.account`: non-secret account ID used as the Keychain account.
- `auth.scopes`: vendor scopes or permissions granted (informational; the vendor enforces them).
- `auth.expires_at`: optional; `null` for non-expiring tokens.
- `auth.status`: `connected`, `needs_setup`, `needs_reconnect`, `app_not_running` (Zotero local), `unavailable`.
- No field ever contains a secret value.
