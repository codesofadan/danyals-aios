# AIOS Citation Assistant

Operator autofill and evidence capture for the citation queue. **Not a bot.**

## What it is, and what it deliberately is not

The operator opens a directory's add-listing form themselves, in their own browser,
signed into their own account. This extension fills the form from the canonical business
profile, the human reviews it and presses submit, and the extension records what actually
happened. It is the posture of a password manager's autofill, not of a crawler.

That framing is a measured decision, not caution. Of the 50 directory form URLs in the
catalogue, **29 return 403 to a scripted client** and 8 return 404; roughly half the
automatable long tail sits behind a WAF, and a 403 is the platform's answer rather than a
puzzle to solve. Meanwhile Yelp, Trustpilot and Houzz ban automated *access* in their
terms, and a form-filling bot must load the page before it can fill it — so the ban binds.

What it does attack is the number that actually costs money: at 100 clients, human queue
time is ~250 hours a year, **56% of the loaded cost per live citation**, and minutes-per-
item is one of only two real levers on that cost. Pre-filling every field and giving one
deep link is what turns five minutes into about ninety seconds.

## Install

```bash
npm install && npm run build      # produces a loadable dist/
```

Then `chrome://extensions` → Developer mode → **Load unpacked** → select `dist/`.

**Do not publish this to the Chrome Web Store.** An extension that fills forms on
third-party sites and uploads screenshots to a private API invites heavy review and can
be pulled at any time — an unacceptable dependency for an internal tool. Distribute a
self-hosted `.crx` by enterprise policy, or load unpacked for a small team.

## Pairing

Mint a token in the dashboard (Settings → Extension), paste it into the panel. It is
shown **once**.

## The credential, honestly

The token lives in `chrome.storage.local`, which is **plaintext on disk** and readable by
anything with filesystem access to the browser profile. That is inherent to an extension
and cannot be engineered away. It is why the token:

- reaches the **citation queue and nothing else** — the scope vocabulary is closed, so no
  scope exists that reaches the vault, the client roster or the cost dials;
- is **not a JWT**, so the dashboard's auth rejects it on every other route by
  construction rather than by remembering to check;
- **expires in twelve hours** — one shift.

**Do not lengthen the TTL for convenience.** The short life is the mitigation for a
storage medium we do not control. Revoke a device from the same settings page; a password
change or a suspension already kills every token that person ever paired.

The directory password is never sent here. The operator signs into the directory once, in
their own browser, and the session lives in their own cookie jar.

## Architecture, and why it is split three ways

| World | Sees the token | Job |
|---|---|---|
| `service-worker.ts` | **yes** | the only code that calls the API |
| `panel.ts` | no | renders state, sends messages |
| `filler.ts` | no | fills the form, reports what stuck |

A content script shares a renderer with whatever JavaScript the directory serves, so it
gets selectors and values and returns an outcome — nothing else. `tests/isolation.test.ts`
asserts this against the **built bundles**, because a bundler is exactly the thing that
can quietly pull a shared import into two chunks.

## The failure this codebase is shaped around

Setting `el.value = x` on a React-controlled input updates the DOM property and nothing
else: React tracks values on an internal `_valueTracker`, its `onChange` never fires, and
the component writes an empty string back on the next render. The operator sees a filled
form, submits, and the directory receives nothing — while the extension reports nine
fields filled.

So `filler.ts` writes through the **prototype's** value setter and then **reads every
value back after a frame**. Without the read-back it is confidently wrong; with it the
panel can say "7 of 9 filled, 2 rejected by the site", which is the truth. Removing the
read-back makes `tests/filler.test.ts` fail — verified, not assumed.

## Known constraints

- **Chrome 114+ and Chromium only.** `chrome.sidePanel` has no Firefox or Safari
  equivalent, and it cannot be opened outside a user gesture.
- The service worker is killed after ~30s idle, so all state lives in
  `chrome.storage.session` and every handler re-hydrates.
- `chrome.alarms` has a **one-minute minimum period**, which is why the server's claim
  lease is twenty minutes rather than two.
