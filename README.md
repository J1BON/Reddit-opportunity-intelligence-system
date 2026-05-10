# Reddit Opportunity Intelligence System

Free, 24/7 bot that watches money-making subreddits for new referral, signup,
and bonus offers, scores them for trust / scam-risk / hidden-gem potential,
and:

- **Posts USA-eligible opportunities into a Discord channel** within minutes
  of them being posted on Reddit.
- **Publishes a live web dashboard** of every offer the bot has ever seen,
  hosted free on GitHub Pages — so you don't have to scroll Discord.

Runs entirely on **free** GitHub Actions cron — no server, no VPS, no
credit card, no Reddit API key, no Reddit account.

> **Web dashboard:** once GitHub Pages is enabled (one click — see step 8
> below), the latest snapshot lives at
> `https://<your-user>.github.io/<your-repo>/` and refreshes itself every
> minute. New offers appear within ~2 minutes of being detected.

---

## What you actually get

A Discord thread, in your own channel, every time something like this shows up:

```text
🔥 NEW USA OPPORTUNITY

Company: Chase
Reward: $500
Requirements: direct_deposit
Deposit Needed: False
States Eligible: USA scope unclear — verify terms
Trust Score: 61.5
Mentions: 4
Trend Velocity: rising
Hidden Gem Score: 58.3

Summary:
[bank_bonus] Chase $500 checking promo — open new account, set up direct deposit ...

Links:
https://reddit.com/r/beermoney/comments/... | https://chase.com/...
```

One thread per offer. Deduped across subs and reposts. 1-hour cooldown per
offer so the same bonus doesn't spam the channel.

---

## How it works

```text
┌──────────────────────────────────────────────────────────────────────────┐
│  GitHub Actions cron — fires every 10 minutes, 24/7                      │
├──────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│   1. Picks which subs to scan this tick (priority sharding):             │
│        • top 12 highest-quality subs → every tick (10 min latency)       │
│        • remaining ~16 subs        → 1 of 3 shards per tick (~30 min)    │
│      Same total Reddit requests as the old 30-min cron, but hot subs     │
│      get checked 3× more often.                                          │
│                                                                          │
│   2. Pulls /new from each chosen sub (Reddit's public JSON, no auth,     │
│      throttled to ~10 req/min, with adaptive backoff on 429)             │
│                                                                          │
│   3. Filters out non-USA offers (UK only / Canada only / EU only / ...)  │
│                                                                          │
│   4. Ingests every post that mentions money, a referral link,            │
│      a promo code, or an early-signal phrase                             │
│                                                                          │
│   5. Scores each one:                                                    │
│      • trust_score (anchor brand, payout-confirmation phrases, ...)      │
│      • scam_probability (suspicious domains, gambling-investment-speak)  │
│      • hidden_gem_score (unknown brand × decent reward × low saturation) │
│      • opportunity_score (composite — used for ranking)                  │
│      • first_mover_score (saturation × novelty × engagement)             │
│                                                                          │
│   6. Dedupes against the canonical-offer table in SQLite                 │
│                                                                          │
│   7. Fires a Discord thread if any of:                                   │
│        • reward ≥ $1                                                     │
│        • opportunity_score ≥ 50                                          │
│        • hidden_gem_score ≥ 70                                           │
│        • urgent + trust ≥ 40                                             │
│        • bank/brokerage/sportsbook ≥ $15                                 │
│        • crypto signup ≥ $25                                             │
│                                                                          │
│   8. Exports docs/offers.json for the web dashboard                      │
│                                                                          │
│   9. Commits the updated SQLite DB + offers.json back to the repo so     │
│      dedupe state survives, and GitHub Pages auto-rebuilds with the      │
│      fresh snapshot                                                      │
│                                                                          │
└──────────────────────────────────────────────────────────────────────────┘
```

Three secondary workflows for one-off tasks:

- `discord-test` — send a test ping to verify Discord wiring
- `discord-diagnose` — list every guild + channel the bot can see, plus
  attempt a real POST with detailed 401/403/404 diagnostics
- `alert-backlog` — flush every alert-eligible canonical offer in the DB
  into Discord, ignoring per-offer cooldown (also runs automatically once
  on the very first cron tick after secrets are configured)

---

## Quick-start (deploy your own copy)

Full walkthrough: **[`DEPLOY_GITHUB_ACTIONS.md`](DEPLOY_GITHUB_ACTIONS.md)**.

Short version, ~10 minutes:

1. **Fork** this repo (top-right "Fork" button). Keep it public for unlimited
   free Actions minutes.
2. **Create a Discord bot** at
   <https://discord.com/developers/applications> → New Application → Bot →
   Reset Token (save it) → OAuth2 URL Generator (scopes: `bot`; permissions:
   View Channel + Send Messages) → invite to your server.
3. **Copy a channel ID** from your server (Discord Settings → Advanced →
   Developer Mode ON → right-click channel → Copy Channel ID).
4. **Add two repo secrets** at
   `https://github.com/<you>/<repo>/settings/secrets/actions`:
   - `DISCORD_BOT_TOKEN` — the token from step 2
   - `DISCORD_ALERT_CHANNEL_ID` — the ID from step 3
5. **Enable Actions** (Actions tab → big green button on a fresh fork).
6. **Allow workflow writes**: Settings → Actions → General → Workflow
   permissions → "Read and write permissions" → Save.
7. **Push any commit** (even a typo fix in this README). That triggers the
   first cron run, which flushes the alert backlog into Discord. From there,
   the every-10-min schedule takes over.
8. **Enable the web dashboard** (one-time):
   - Settings → Pages
   - Source: **Deploy from a branch**
   - Branch: **main**, Folder: **`/docs`** → Save
   - After ~1 minute, your dashboard goes live at
     `https://<your-user>.github.io/<your-repo>/` and auto-rebuilds every
     time the cron commits a fresh `docs/offers.json` (≈ every 10 min).

---

## Configuration

All knobs live in **`.github/workflows/intel-cron.yml`** under the
"Run one fetch cycle" step's `env:` block. Edit, commit, push — the push
trigger fires a new run immediately with the new values.

| Variable | Default | Effect |
|---|---|---|
| `USA_ONLY_STRICT` | `1` | Drop posts that explicitly exclude USA (UK only / Canada only / EU only / international only / non-US / worldwide except). Set `0` to ingest everything. |
| `ALERT_MIN_PAYOUT_USD` | `1` | Minimum detected dollar amount in the post body to trigger an alert via the reward criterion. |
| `ALERT_MIN_OPPORTUNITY_SCORE` | `50` | Composite-score threshold for alerts on posts without a clean dollar amount. Higher → fewer, more confident alerts. |
| `BACKFILL_INTERVAL_SECONDS` | `1800` | Internal cooldown for re-scoring the same offer. |
| `POSTS_PER_SUB_FETCH` | `25` | How many newest posts per sub per cron tick. Higher → broader coverage, more chance of 429. |
| `FETCH_COMMENT_SAMPLES` | `0` | Set `1` to also scan comment trees for payout-confirmation phrases (strong signal, doubles request volume). |

Subreddits live in **`reddit_intel/config.py`**:

- `HIGH_PRIORITY_SUBREDDITS` — the 28 monitored subs
- `EXCLUDED_SUBREDDITS` — never monitor these

Cron cadence lives in **`.github/workflows/intel-cron.yml`** at
`schedule: - cron: "*/10 * * * *"`. Change to `0 * * * *` for hourly,
`*/30 * * * *` for every 30 min, etc.

Sharding (hot vs cold subs per tick) is in **`reddit_intel/engine.py`**
inside `_shard_subs(ranked, hot_count=12, shards=3)`. Increase `hot_count`
to scan more subs every tick at the cost of more Reddit API pressure;
increase `shards` to lower per-tick API load (worst-case cold latency
becomes `cron_interval × shards`).

---

## Local development

Run the same code on your PC:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
py -3 -m pip install -r requirements.txt
copy .env.example .env       # then fill in REDDIT_NO_AUTH=1 and your Discord vars
py -3 run.py --once
```

If your ISP blocks Reddit (common on some networks), turn on Cloudflare WARP
first. The GitHub Actions runner doesn't have this problem — that's why we
host it there.

For all flags and tuning, see **[`RUNBOOK.md`](RUNBOOK.md)**.

---

## Project layout

```text
run.py                              entry shim
requirements.txt                    praw + python-dotenv
.github/workflows/
  intel-cron.yml                    main 10-min cron (+ auto-backlog + dashboard export)
  discord-test.yml                  ping Discord (manual)
  discord-diagnose.yml              list bot's guilds/channels (manual)
  alert-backlog.yml                 flush backlog (manual)
reddit_intel/
  main.py                           CLI: --once / --daemon / --report
  reddit_client.py                  PRAW or no-auth public client selector
  public_client.py                  no-auth Reddit JSON client
  engine.py                         fetch → ingest → score → alert (+ sub sharding)
  config.py                         subs, keywords, thresholds
  detectors.py                      money / keyword / URL / USA-filter regexes
  scoring.py                        trust / scam / gem / opportunity formulas
  intelligence_signals.py           engagement / saturation / fatigue signals
  entity_intel.py                   brand / domain / launch-status heuristics
  comment_intel.py                  comment-tree confirmation scanning
  alerts.py                         Discord (bot + webhook) + console output
  database.py                       SQLite persistence + migrations
  dedupe.py                         canonical-offer ID generation
  report_builder.py                 markdown report generator
  url_probe.py                      optional HEAD-probe for link health
  throttle.py                       adaptive backoff under Reddit 429
scripts/
  alert_backlog.py                  flush eligible canonical offers to Discord
  export_dashboard.py               canonical_offers → docs/offers.json
docs/                               GitHub Pages site (static, no build)
  index.html                        dashboard markup
  styles.css                        dark theme
  app.js                            filter / sort / search / auto-refresh
  offers.json                       auto-generated by cron
data/
  reddit_intel.db                   SQLite state — committed between runs
reports/
  intel_<unix>.md                   periodic markdown rollups
```

---

## What it's NOT

- **Not a Reddit firehose.** It polls `/new` every 10 minutes (every 30 min
  for cold subs in shard rotation), capped at ~25 posts/sub. Posts that get
  buried before the next poll will be missed.
- **Not financial advice.** Every alert is just text-mined data with
  imperfect heuristic scoring. Verify offer terms before signing up; verify
  domain legitimacy before clicking referral links; assume nothing.
- **Not a spam/account farm.** It only reads public listings; it doesn't
  comment, vote, post, or DM. It does not need a Reddit account.
- **Not real-time.** Up to 10 min for hot subs (worst case 30 min for cold
  subs) between a post appearing on Reddit and the corresponding alert
  hitting Discord / dashboard.
- **Not a private dashboard.** The web dashboard is served from public
  GitHub Pages and shows the same data that's already public on Reddit.
  Don't store anything secret in it — there are no referral codes or PII
  in `docs/offers.json`.

---

## License

MIT — do whatever you want with this code. No warranty.
