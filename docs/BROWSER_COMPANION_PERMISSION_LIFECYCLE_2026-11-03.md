# Browser Companion — user-granted permission lifecycle (2026-11-03)

## Change

The opt-in TraceCart MV3 extension v0.2.1 now exposes three explicit
per-merchant actions in its popup:

- **Grant access to this shop**: initiates Chromium's native
  `chrome.permissions.request` dialog from a direct user click.
- **Check site permission**: reads `chrome.permissions.contains`.
- **Revoke access to this shop**: uses `chrome.permissions.remove`,
  then independently checks the actual permission state.

All operations accept **only a public-style HTTPS merchant origin**,
extracted from the pasted product URL. They reject HTTP, credentials,
explicit ports, loopback IPs, local/internal hostnames and invalid origins.
No wildcard host access is granted by default; the extension's original
optional `https://*/*` capability is unchanged and requests are site-scoped.

Revocation does **not** delete previously recorded research results, and
does not need to stop the entire queue. The service worker checks the
site's permission before opening a tab, **again after the tab loads**,
and **again after extraction before returning the projection**.
If a grant is removed during an in-flight task, the result is
`SITE_PERMISSION_REQUIRED` with no product fields. A queued job whose
permission was removed is not retried automatically.

The worker never requests or reinstates permissions on its own. A new
grant can occur only through the extension's explicit user-facing
**Grant access** action. Chromium may remember a previously approved
origin and approve a *subsequent user-initiated request* without displaying
a new modal, even after `permissions.remove`: disabling the queue stops
research globally; revocation stops research for a specific merchant
until separately reauthorized.

## Reproducible real native Chromium UI test

`benchmarks/browser_permission_ui_e2e.py` is an **opt-in test** of the
actual Chromium extension popup and native permission modal, rather than
a mock of `chrome.permissions`.

On hexagony-01, it launches a disposable Chromium profile and a copy of
the **unmodified** extension manifest inside isolated Xvfb display
`1080 × 1000`, with real Chrome MV3 service worker. Programmatic trusted
input into the extension popup triggers Chromium's real permission prompt.
X11 XTest mouse events click the native dialog's **Deny** and **Allow**
buttons. The test then clicks **Revoke** in the extension popup,
checks the browser permission state, and submits a queued product URL to an
isolated loopback TraceCart broker. The real service worker correctly
returns `SITE_PERMISSION_REQUIRED` without product evidence.

This is test automation of a synthetic, disposable browser with a
controlled public test origin; it is **not** consent granted by a human user
in their normal browser. No user browser profile, cookies, merchant account
or production TraceCart server are used. The native prompt pixel
coordinates are deliberately fixed to the declared test display size;
a change in Chromium UI layout can cause a visible test failure rather
than false success.

Requires Chromium Snap, `xvfb-run`, Python `websocket-client`,
X11 libraries `libX11`, `libXtst`, and `openssl` when applicable.
Requires explicit selection of the public Adafruit case. Before testing,
the existing source adapter checks public HTTPS access and robots rules:

```bash
cd /mnt/nvme_fast/tracecart
xvfb-run -a -s '-screen 0 1080x1000x24' \
  python3 benchmarks/browser_permission_ui_e2e.py --public-adafruit
```

### Observed result (2026-11-03)

| Scenario | Actual Chrome permission state | TraceCart |
|---|---|---|
| Fresh profile, click native **Deny** | false | No merchant access |
| Request again, click native **Allow** | true | Permission available |
| Click popup **Revoke** | false | Permission removed |
| Queue Adafruit #1083 after revoke | false | `SITE_PERMISSION_REQUIRED`; no evidence |

Result: `REAL_NATIVE_CHROMIUM_DENY_GRANT_REVOKE_PASS`;
`POST_REVOKE_QUEUE_BLOCKED SITE_PERMISSION_REQUIRED`.

Separate Node tests validate all helper methods and rejection of
nonpublic URLs, plus revocation while a tab is loading and while fields
are being collected. Existing regression and MV3 E2E tests still apply.

## Limitations

- A `permissions.remove` operation cannot retroactively erase already
  saved evidence; the research UI must keep showing source provenance.
- Existing active browser requests cannot be undone; checks before
  extracting and returning data prevent later product claims after revoke.
- This is a permission safety gate, not a solution for an inaccessible
  merchant page, CAPTCHA or restricted content.
- The queue remains in-memory in v1; persistence, broader retailer
  coverage, reliable variant/seller matching and checkout verification
  are independent future tasks.
- No paid API calls, GitHub Actions, password/cookie export,
  payment actions or production deployment in this increment.
