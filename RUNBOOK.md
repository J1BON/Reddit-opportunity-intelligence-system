# Reddit Opportunity Intelligence — Runbook (A–Z)

End-to-end guide to install, configure, run, and tune **USA Reddit Opportunity Intelligence** on Windows (also works on macOS/Linux with the same commands using `python3`).

---

## What this tool does

- Polls **priority subreddits** for referral/signup/bonus-style posts.
- **Dedupes** overlapping posts into canonical offers, scores them (trust, scam risk, hidden gem, first mover, etc.).
- Optionally scans **sample comments** for payout-confirmation phrases.
- Tracks **external domains** (first-seen, mention spread) for early-gem detection.
- Writes everything to a **local SQLite** database and optional **markdown reports**.
- Can print alerts to the console, post to a **webhook**, or send with a **Discord bot** into a channel.

This is **not** real-time Reddit firehose access; it uses Reddit’s API with a configurable polling interval. Efficiency is bounded by **Reddit rate limits**, network latency, and how many subs/posts/comments you touch per cycle.

---

## Prerequisites

| Requirement | Notes |
|-------------|--------|
| **Python 3.10+** | On Windows, use `py -3` if `python` is not on PATH. |
| **Reddit account** | Optional. Required only for **Mode A (OAuth)** below. |
| **Reddit “script” app** | Optional. Required only for **Mode A (OAuth)**. Created at [reddit.com/prefs/apps](https://www.reddit.com/prefs/apps) → “create another app…” → type **script**. |

> **No API key? You can still run.** See **Mode B (no-auth)** in section **D**. The bot
> will read Reddit's public `/r/<sub>/new.json` endpoints directly — no app, no
> username, no password — at the cost of a tighter ~10-requests/minute shared
> rate limit.

> **Want 24/7 alerts without leaving your PC on?** See
> **[`DEPLOY_GITHUB_ACTIONS.md`](DEPLOY_GITHUB_ACTIONS.md)** — runs this bot on
> a free GitHub Actions cron, posts hits to your Discord, no credit card, no
> VPS. The same cron publishes a **free static web dashboard** at
> `https://<your-user>.github.io/<your-repo>/`.
>
> ⚠️ **Reddit blocks the GitHub Actions IP range on the public JSON endpoints**
> (both `www.reddit.com` and `old.reddit.com` return `HTTP 403 Blocked`).
> When running in Actions you **must** use OAuth — add four secrets to
> `Settings > Secrets and variables > Actions`:
>
> - `REDDIT_CLIENT_ID` — 14-char string under your app name at
>   <https://www.reddit.com/prefs/apps> (type **script**, redirect URI
>   `http://localhost:8080`)
> - `REDDIT_CLIENT_SECRET` — `secret` field of the same app
> - `REDDIT_USERNAME` — your Reddit username
> - `REDDIT_PASSWORD` — your Reddit password
>
> `reddit_intel/reddit_client.py::make_reddit()` switches to PRAW automatically
> the moment all four exist. The bot also posts an `ACTION REQUIRED` heartbeat
> to Discord whenever a cycle is 100% 403-blocked, so you'll never wonder why
> the dashboard is frozen.

---

## Web dashboard (GitHub Pages)

When the cron runs, it writes `docs/offers.json` (a slimmed snapshot of the
`canonical_offers` table) and commits it. GitHub Pages serves `docs/index.html`
which fetches `offers.json` client-side every 60 seconds.

To enable Pages on a new fork:

1. Repo → **Settings** → **Pages**
2. Source: **Deploy from a branch**
3. Branch: **`main`**, Folder: **`/docs`** → **Save**

After ~60–90 seconds, your dashboard is live. It auto-rebuilds every cron tick.

Local preview without GitHub Pages:

```powershell
py -3 -m scripts.export_dashboard            # writes docs/offers.json
py -3 -m http.server 8765 --directory docs   # browse http://127.0.0.1:8765/
```

The dashboard is **fully static** — no backend, no DB connection from the
browser. To change layout / colors, edit `docs/index.html`, `docs/styles.css`,
`docs/app.js`. To change which fields ship to the UI, edit `_row_to_offer()`
in `scripts/export_dashboard.py`.

---

## 0 — Sanity check: can your machine reach Reddit at all?

Before anything else, confirm Reddit is reachable from this network. From a
PowerShell prompt:

**Use `curl.exe` with Windows-safe flags** (not `-o $null` — that breaks `curl`
and can trigger `Malformed input to a URL function` / write errors; discard the
body with `-o NUL` instead). Put the URL **after** `-o` and `-w` so nothing is
parsed as a second URL:

```powershell
curl.exe -sS --connect-timeout 8 -o NUL -w "STATUS=%{http_code}`n" https://www.reddit.com/
curl.exe -sS --connect-timeout 8 -o NUL -w "STATUS=%{http_code}`n" https://example.com/
```

In the `-w` string, the newline is a **PowerShell** escape: backtick + `n`
(`` `n ``), not backslash + `n`.

**Alternative (pure PowerShell):**

```powershell
(Invoke-WebRequest -Uri "https://example.com/" -UseBasicParsing -TimeoutSec 8).StatusCode
(Invoke-WebRequest -Uri "https://www.reddit.com/" -UseBasicParsing -TimeoutSec 8).StatusCode
```

- If both commands succeed with **200**, you're good — continue to **A** (`curl`
  prints `STATUS=200`; `Invoke-WebRequest` prints just `200`).
- If `example.com` returns 200 but Reddit returns `STATUS=000` / "Connection reset" /
  "Connection timed out", **your network is blocking Reddit** (common on some
  ISPs, schools, corporate networks, certain countries). No API key, no code
  change, and no `pip install` will fix this — Reddit's packets are being
  dropped before any auth happens. See **Troubleshooting → "Connection reset"**
  in section **L** for VPN / hotspot / cloud-VM / proxy workarounds.

---

## A — Clone or open the project

Your project root should contain:

- `run.py` — main entry shim  
- `requirements.txt`  
- `reddit_intel/` — package  
- `.env.example` — template for secrets  

---

## B — Create a virtual environment (recommended)

From the project folder (`RedditBot`):

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
py -3 -m pip install --upgrade pip
py -3 -m pip install -r requirements.txt
```

macOS/Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

---

## C — Create the Reddit API application

1. Log in to Reddit in the browser.  
2. Open [reddit.com/prefs/apps](https://www.reddit.com/prefs/apps).  
3. **Create another app…**  
   - **name**: anything you recognize  
   - **type**: **script**  
   - **redirect uri**: `http://localhost:8080` (placeholder; unused for script password flow)  
4. Note **client ID** (under the app name) and **secret**.

---

## D — Configure `.env`

1. Copy `.env.example` to `.env` in the **project root** (same folder as `run.py`).
2. Choose one of the two modes below.

### Mode A — OAuth (PRAW). Preferred when you can register a Reddit app.

| Variable | Required | Meaning |
|----------|----------|---------|
| `REDDIT_CLIENT_ID` | Yes | Script app client ID |
| `REDDIT_CLIENT_SECRET` | Yes | Secret |
| `REDDIT_USERNAME` | Yes | Reddit username |
| `REDDIT_PASSWORD` | Yes | Reddit password |
| `REDDIT_USER_AGENT` | Yes | Unique string, e.g. `USAIntelBot/1.0 by YourUsername` — **must be descriptive** per Reddit rules |

Higher rate limits, full PRAW feature set.

### Mode B — No-auth public JSON. Use when you can't get API credentials.

Leave the four `REDDIT_CLIENT_*` / `REDDIT_USERNAME` / `REDDIT_PASSWORD` values
blank **or** set `REDDIT_NO_AUTH=1`. The bot will fetch from
`https://www.reddit.com/r/<sub>/new.json` directly. No app, no login.

Trade-offs and recommended tuning:

| Setting | Recommended in no-auth mode | Why |
|---------|------------------------------|-----|
| `REDDIT_USER_AGENT` | Still set to something descriptive | Reddit blocks empty/default UAs |
| `BACKFILL_INTERVAL_SECONDS` | `900` or higher | Reddit allows ~10 req/min unauthenticated; one cycle of N subs ≥ N requests |
| `FETCH_COMMENT_SAMPLES` | `0` | Each comment scan is a second request per qualifying post — easy to trip 429 |
| `POSTS_PER_SUB_FETCH` | `25–50` | Same listing call covers up to 100, but trim if you see 429 |

You will see this on stderr in no-auth mode:

```text
[reddit] No OAuth credentials (...). Falling back to public JSON endpoints
(no auth, ~10 req/min limit). Set REDDIT_NO_AUTH=0 and fill .env to enable PRAW.
```

That message means the public client is working as designed.

Optional:

| Variable | Default | Meaning |
|----------|---------|---------|
| `ALERT_WEBHOOK_URL` | empty | Discord/Slack webhook URL for alerts |
| `DISCORD_BOT_TOKEN` | empty | Bot token from [Discord Developer Portal](https://discord.com/developers/applications) |
| `DISCORD_ALERT_CHANNEL_ID` | empty | Numeric channel ID where the bot may send messages |
| `BACKFILL_INTERVAL_SECONDS` | `300` | Seconds between daemon poll cycles |
| `REPORT_INTERVAL_SECONDS` | `43200` (12h) | Daemon report period **and** report window length |
| `POSTS_PER_SUB_FETCH` | `50` | `/new` posts per subreddit per cycle |
| `FETCH_COMMENT_SAMPLES` | `1` | Set `0` to **skip comment trees** (fastest; weaker confirmation signal) |
| `COMMENT_SAMPLE_LIMIT` | `40` | Max comments scanned per post when comments enabled |
| `ALERT_MIN_PAYOUT_USD` | `20` | Standard alert threshold |
| `ALERT_MIN_OPPORTUNITY_SCORE` | `75` | Standard alert threshold |
| Early gem tuning | see `.env.example` | **No minimum payout** — early gems do **not** require a dollar amount in text |

---

## E — First run (single cycle)

From project root with venv activated:

```powershell
py -3 run.py
```

With no flags, this runs **one fetch cycle** then exits.  
Stderr shows how many matching posts were processed.

---

## F — Run continuously (daemon)

```powershell
py -3 run.py --daemon
```

- Fetches on `BACKFILL_INTERVAL_SECONDS`.  
- Writes a markdown report every `REPORT_INTERVAL_SECONDS` under `reports/`.  

Stop with **Ctrl+C**.

---

## G — Reports only (no Reddit fetch)

Uses existing SQLite data:

```powershell
py -3 run.py --report
```

Optional custom window:

```powershell
py -3 run.py --report --report-window-hours 24
```

Reports are printed to stdout and saved under `reports/intel_<timestamp>.md`.

---

## H — Combined: report + one fetch

```powershell
py -3 run.py --report --once
```

---

## I — Where data lives

| Path | Purpose |
|------|---------|
| `data/reddit_intel.db` | SQLite: posts, canonical offers, domains, alerts log |
| `reports/` | Generated markdown intelligence reports |

Back up `reddit_intel.db` if you care about history.

---

## J — Alerts

- **Standard** (“NEW USA OPPORTUNITY”) — thresholds: `ALERT_MIN_PAYOUT_USD`, `ALERT_MIN_OPPORTUNITY_SCORE`, etc. Cooldown **1 hour** per canonical offer (`standard` alert kind).  
- **Early gem** (“EARLY GEM DETECTED”) — unknown brand and/or **first-seen domain** in corpus, plus first-mover/saturation/trust/scam gates. **There is no minimum payout.** Cooldown **2 hours** per canonical (`early_gem` alert kind).

If `ALERT_WEBHOOK_URL` is set, both alert types POST JSON `{"content": "..."}` (Discord-compatible).

If `DISCORD_BOT_TOKEN` and `DISCORD_ALERT_CHANNEL_ID` are set, the same alert text is posted via Discord’s REST API (`POST /channels/{id}/messages`). Messages longer than 2000 characters are split into multiple posts.

**Discord bot setup (quick):** Create an application → Bot → reset/copy token → OAuth2 URL Generator: scopes **`bot`**, permission **Send Messages** → invite the bot to your server → enable **Developer Mode** in Discord (Advanced settings) → right‑click the target channel → **Copy Channel ID** → paste into `DISCORD_ALERT_CHANNEL_ID`.

You can use **webhook**, **Discord bot**, **both**, or neither (console-only).

---

## K — Efficiency and “100% toward your goal”

You cannot hit literal **100%** capture of every Reddit opportunity because:

1. Reddit does not expose an unrestricted real-time stream for arbitrary subs via basic OAuth script apps.  
2. **Rate limits** cap requests; aggressive parallelism can get you throttled or banned.  
3. You only fetch **`POSTS_PER_SUB_FETCH` newest posts** per sub each cycle — very old or buried threads may be missed until something bumps them.

**Practical tuning for speed vs coverage:**

| Goal | Suggestion |
|------|------------|
| **Fast cycles** | Lower `POSTS_PER_SUB_FETCH` (e.g. `25`), increase `BACKFILL_INTERVAL_SECONDS` slightly so you don’t hammer the API. |
| **Maximum speed** | `FETCH_COMMENT_SAMPLES=0` — skips comment API calls entirely. |
| **Stronger payout signals** | `FETCH_COMMENT_SAMPLES=1` (default) and optionally raise `COMMENT_SAMPLE_LIMIT` slightly (more API cost). |
| **Broader net** | Raise `POSTS_PER_SUB_FETCH`; watch for 429 errors — back off if needed. |

The codebase avoids redundant work where cheap to do so (e.g. **domain tracking** skips DB domain upserts when there are no external URLs; **comment scan** only runs on first link of a post to an offer).

---

## L — Troubleshooting

| Symptom | What to check |
|---------|----------------|
| `Missing env: REDDIT_*` | `.env` path is project root; variable names exact; no quotes issues |
| `401` / auth failures | Wrong password; 2FA — Reddit script apps need **app password** if 2FA on ([reddit.com/prefs/apps](https://www.reddit.com/prefs/apps) → password) |
| `429` / Too Many Requests | Reduce subs fetched per cycle, increase `BACKFILL_INTERVAL_SECONDS`, set `FETCH_COMMENT_SAMPLES=0` |
| `429` in **no-auth mode** | Expected if you push >10 req/min. Raise `BACKFILL_INTERVAL_SECONDS` to `900+`, set `FETCH_COMMENT_SAMPLES=0`. The bot also auto-defers throttled subs and retries them next cycle. |
| `Connection reset` / `WinError 10054` / `Connection timed out` on every Reddit URL, **even though** other sites and `ping www.reddit.com` work | Your network blocks Reddit at the TLS/SNI layer (common on some ISPs, schools, corporate networks, and certain countries). This is **not** an API or code problem. **Diagnose:** run `curl https://www.reddit.com/` and `curl https://example.com/` — if Reddit fails but example.com works, the network is filtering Reddit. **Fix options:** use a VPN that exits in a region where Reddit is allowed (Mullvad/ProtonVPN/etc.), tether to a mobile hotspot, run the bot on a cloud VM (Oracle free tier, Fly.io, Render, Lightsail), or set `HTTPS_PROXY=http://user:pass@proxyhost:port` before launching `run.py` to route through a proxy. |
| Empty DB / zero processed | Subs may have no matching posts; loosen ingest by posting test keywords; verify monitors list in `reddit_intel/config.py` |
| Webhook errors | URL correct; Discord expects `/api/webhooks/...`; firewall |
| Discord bot `401` / `403` | Token correct; bot invited; bot role can **Send Messages** in that channel |

---

## M — Compliance

Use one Reddit account you control. Follow [Reddit’s Developer Terms](https://redditinc.com/policies/developer-terms) and [API rules](https://support.reddithelp.com/hc/en-us/articles/16160319855892-Reddit-API-Rules). Do not use this to harass, spam, or violate subreddit rules. Offers mentioned are **not financial advice**; verify every program yourself.

---

## N — Quick reference (CLI)

| Command | Behavior |
|---------|----------|
| `py -3 run.py` | One fetch cycle |
| `py -3 run.py --once` | Same as above (explicit) |
| `py -3 run.py --daemon` | Poll forever + periodic reports |
| `py -3 run.py --report` | Report from DB, exit (unless also `--once` / `--daemon`) |
| `py -3 run.py --report --once` | Report then one fetch |

Alternative module form:

```powershell
py -3 -m reddit_intel.main --daemon
```

---

## O — Updating after pulling new code

```powershell
py -3 -m pip install -r requirements.txt
py -3 run.py --once
```

SQLite migrations run automatically on startup when `Database()` initializes.

---

You now have an A–Z path from **install → credentials → first run → daemon → reports → tuning**. Adjust `.env` until your cycle time and API usage match how aggressively you want to hunt opportunities without tripping limits.
