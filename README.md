# Reddit Opportunity Intelligence System

Free, 24/7 bot that watches money-making subreddits for new referral, signup,
and bonus offers, scores them for trust / scam-risk / hidden-gem potential,
and posts USA-eligible opportunities into a Discord channel within minutes
of them being posted on Reddit.

Runs entirely on **free** GitHub Actions cron — no server, no VPS, no
credit card, no Reddit API key, no Reddit account.

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
│  GitHub Actions cron — fires every 30 minutes, 24/7                      │
├──────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│   1. Pulls latest /new from 28 monitored subreddits                      │
│      (Reddit's public JSON, no auth, throttled to ~10 req/min)           │
│                                                                          │
│   2. Filters out non-USA offers (UK only / Canada only / EU only / ...)  │
│                                                                          │
│   3. Ingests every post that mentions money, a referral link,            │
│      a promo code, or an early-signal phrase                             │
│                                                                          │
│   4. Scores each one:                                                    │
│      • trust_score (anchor brand, payout-confirmation phrases, ...)      │
│      • scam_probability (suspicious domains, gambling-investment-speak)  │
│      • hidden_gem_score (unknown brand × decent reward × low saturation) │
│      • opportunity_score (composite — used for ranking)                  │
│      • first_mover_score (saturation × novelty × engagement)             │
│                                                                          │
│   5. Dedupes against the canonical-offer table in SQLite                 │
│                                                                          │
│   6. Fires a Discord thread if any of:                                   │
│        • reward ≥ $1                                                     │
│        • opportunity_score ≥ 50                                          │
│        • hidden_gem_score ≥ 70                                           │
│        • urgent + trust ≥ 40                                             │
│        • bank/brokerage/sportsbook ≥ $15                                 │
│        • crypto signup ≥ $25                                             │
│                                                                          │
│   7. Commits the updated SQLite DB back to the repo so dedupe,           │
│      alert cooldowns, and domain first-seen state survive between runs   │
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
   the every-30-min schedule takes over.

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
`schedule: - cron: "*/30 * * * *"`. Change to `0 * * * *` for hourly,
`*/15 * * * *` for every 15 min, etc.

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
  intel-cron.yml                    main 30-min cron (+ auto-backlog)
  discord-test.yml                  ping Discord (manual)
  discord-diagnose.yml              list bot's guilds/channels (manual)
  alert-backlog.yml                 flush backlog (manual)
reddit_intel/
  main.py                           CLI: --once / --daemon / --report
  reddit_client.py                  PRAW or no-auth public client selector
  public_client.py                  no-auth Reddit JSON client
  engine.py                         fetch → ingest → score → alert
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
data/
  reddit_intel.db                   SQLite state — committed between runs
reports/
  intel_<unix>.md                   periodic markdown rollups
```

---

## What it's NOT

- **Not a Reddit firehose.** It polls `/new` every 30 minutes, capped at
  ~25 posts/sub. Posts that get buried before the next poll will be missed.
- **Not financial advice.** Every alert is just text-mined data with
  imperfect heuristic scoring. Verify offer terms before signing up; verify
  domain legitimacy before clicking referral links; assume nothing.
- **Not a spam/account farm.** It only reads public listings; it doesn't
  comment, vote, post, or DM. It does not need a Reddit account.
- **Not real-time.** Up to 30 min between a post appearing on Reddit and
  the corresponding alert hitting Discord.

---

## License

MIT — do whatever you want with this code. No warranty.
