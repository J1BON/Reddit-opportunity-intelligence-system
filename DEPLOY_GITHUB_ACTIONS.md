# Deploy to GitHub Actions (free 24/7)

This guide turns your bot into a fully-managed, always-on cron job hosted by
GitHub. It runs every 30 minutes from GitHub's clean datacenter network (so
**no WARP needed**), posts hits to your Discord channel, and commits the
SQLite DB back to your repo so dedupe + alert cooldowns survive across runs.

**Cost:** $0. **Credit card:** not required. **Your PC:** can be off.

---

## What you'll do (10 minutes total)

1. Create a Discord bot and get its token + channel ID. (5 min)
2. Create an empty private repo on GitHub. (1 min)
3. Push this folder to that repo. (2 min)
4. Add the Discord secrets to the repo. (2 min)
5. Watch the workflow run.

---

## 1. Create the Discord bot

You'll need a server you can administer. If you don't have one, open Discord
→ "+" on the left rail → **Create My Own** → pick a server name. (Free, private,
nobody else has to join.)

1. Go to <https://discord.com/developers/applications> → **New Application** →
   name it anything (e.g. `RedditIntelBot`) → **Create**.
2. Sidebar → **Bot** → **Reset Token** → **Copy**. Save this — it's
   `DISCORD_BOT_TOKEN`. You will not see it again.
3. Sidebar → **OAuth2** → **URL Generator** →
   - Scopes: check **`bot`**
   - Bot Permissions: check **Send Messages**, **Embed Links**, **Read Message History**
   - Copy the **Generated URL** at the bottom, open it in your browser,
     pick your server, **Authorize**.
4. In Discord, **User Settings** → **Advanced** → enable **Developer Mode**.
   Right-click the channel where you want alerts → **Copy Channel ID**. Save
   this — it's `DISCORD_ALERT_CHANNEL_ID` (a long number).

---

## 2. Create the GitHub repo (free, private)

1. <https://github.com/new>
2. Owner: your account.
3. Repository name: anything, e.g. `reddit-intel`.
4. Visibility: **Private**.
5. **Do NOT** add a README, .gitignore, or license — we already have those.
6. **Create repository**. You'll land on an empty repo with push instructions.

---

## 3. Push this folder to the repo

From PowerShell, **in the project root** (`C:\Users\MONEY-MACHINE\Desktop\RedditBot`):

```powershell
# Install git if needed: https://git-scm.com/download/win
git --version

# First-time only — tell git who you are.
git config --global user.name  "Your Name"
git config --global user.email "you@example.com"

# Initialise the repo and push.
git init
git add .
git status                                  # sanity-check: .env must NOT appear
git commit -m "Initial commit"
git branch -M main
git remote add origin https://github.com/<YOUR_USERNAME>/<REPO_NAME>.git
git push -u origin main
```

> **Why `.env` is safe.** `.gitignore` in this repo already excludes `.env`,
> so your Discord token and any future Reddit credentials stay on your local
> machine. Confirm `git status` does not list `.env` before the first commit.
> Secrets in GitHub go in *repo settings*, not in any file.

---

## 4. Add the secrets

On the repo page in your browser:

**Settings** → **Secrets and variables** → **Actions** → **New repository secret**.
Create these:

| Secret name | Value |
|---|---|
| `DISCORD_BOT_TOKEN` | The token you copied in step 1.2 |
| `DISCORD_ALERT_CHANNEL_ID` | The numeric channel ID from step 1.4 |
| `ALERT_WEBHOOK_URL` *(optional)* | A Discord/Slack webhook URL, if you also want webhook alerts |

That's it. The workflow file (`.github/workflows/intel-cron.yml`) already
references these names.

---

## 5. Trigger and watch the first run

The cron schedule (`*/30 * * * *`) fires every half hour, but GitHub also lets
you kick it off manually so you don't have to wait.

1. Open your repo → **Actions** tab.
2. If you see a banner saying workflows are disabled on a fresh fork/clone,
   click **I understand my workflows, go ahead and enable them**.
3. Left sidebar → **Reddit Intel cron** → **Run workflow** → **Run workflow**.
4. Click the new run to watch logs stream live. Expected output near the end:

```text
[reddit] REDDIT_NO_AUTH=1 — using public JSON endpoints (no OAuth, rate-limited).
[cycle] ingested/processed N matching posts
```

5. If any post crossed an alert threshold, you'll see a `[ALERT] ...` message
   in Discord within seconds.

After the run finishes, GitHub Actions will commit the updated
`data/reddit_intel.db` (and any `reports/intel_*.md`) back to your repo as
`github-actions[bot]`. That's how state — dedupe, alert cooldowns, domain
first-seen — persists across runs.

---

## Day-to-day

- **Check alerts:** your Discord channel.
- **Look at history:** open `data/reddit_intel.db` in any SQLite viewer
  ([DB Browser for SQLite](https://sqlitebrowser.org/) is fine), or pull the
  repo locally with `git pull` after any cron run.
- **On-demand 24h report:** Actions tab → **Reddit Intel cron** → **Run workflow** →
  set `report` to `true` → **Run workflow**. A markdown report lands in
  `reports/` and is committed back.
- **Pause the bot:** Actions tab → **Reddit Intel cron** → `...` menu →
  **Disable workflow**. Re-enable any time.
- **Pull state to your PC:** `git pull` in this folder; SQLite + reports come
  with it.

---

## Free-tier budget math

| | Cost / month |
|---|---|
| Per-run wall time | ~2 min |
| Runs/day at every 30 min | 48 |
| Runs/month | ~1,440 |
| Action-minutes/month | **~2,880** |
| GitHub free private quota | 2,000 |

That puts you slightly over the **private** free quota. Three painless fixes,
in order of preference:

1. **Set the repo to PUBLIC** → unlimited free Actions minutes. Your `.env`
   never gets pushed (it's gitignored), so the only sensitive data on GitHub
   would be the SQLite DB. Secrets stay encrypted regardless of visibility.
2. **Drop cadence to every 60 min** in `.github/workflows/intel-cron.yml`:
   change `cron: "*/30 * * * *"` to `cron: "0 * * * *"`. ~1,440 minutes/month —
   comfortably under the private free quota.
3. **Skip pip install on every run** by caching the venv (already enabled via
   `setup-python`'s `cache: "pip"`). On a cold run install is ~30 s; on warm
   runs ~5 s. Already done.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| Workflow log shows `[reddit] No OAuth credentials` and then exits with a 429 storm | Expected behaviour on rate-limit; the bot defers throttled subs. If it persists, raise the cron cadence to 60 min. |
| Discord channel is silent even though log shows `[ALERT]` | Bot isn't a member of that server / channel, or `Send Messages` permission missing. Re-run the OAuth invite URL (step 1.3) and make sure the channel ID matches the channel the bot can see. |
| `Permission denied` when the workflow tries to push state | Repo → **Settings** → **Actions** → **General** → **Workflow permissions** → select **Read and write permissions** → **Save**. |
| Workflow never runs on cron, only manually | GitHub disables `schedule:` triggers on inactive repos after ~60 days with zero commits. Any commit re-enables them. |
| `CONFLICT (content): Merge conflict in data/reddit_intel.db` / failed push after `git pull --rebase` | Fixed in current `intel-cron.yml` — update your repo to the latest workflow (pull this project or re-copy `.github/workflows/intel-cron.yml`). The commit step no longer rebases SQLite; it snapshots, resets to `origin/main`, reapplies, then pushes. |
| `[cycle] ingested/processed 0 matching posts` | Normal when nothing new matched your keyword filters in that window, or many subs were deferred (429). Check earlier log lines for rate-limit messages. |

---

## Switching back to local-only later

Nothing locks you in. To run from your PC again, just keep WARP on and:

```powershell
py -3 run.py --once     # or --daemon
```

Your local `.env` is still there with `REDDIT_NO_AUTH=1`. After Actions runs,
`git pull` in this folder downloads the latest committed DB and reports to
your PC (if you edited the DB locally too, Git may warn about conflicts —
pick one copy of `data/reddit_intel.db` and keep it).
