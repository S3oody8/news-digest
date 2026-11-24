# News Digest Agent

A personal news agent built on Claude Code. It sends to Telegram:

- **Morning digest** every day around 8:00 AM Dubai: 10 to 12 stories, each with an image, a punchy headline and a 3-line summary.
- **Breaking alerts** checked every hour from 6 AM to midnight Dubai. It only sends when a story clears the strict "breaking" bar in `news-brief.md`, and never sends the same story twice.

It runs for free on GitHub Actions. You only pay for Claude usage.

```
GitHub Actions (cron)
   └─ scripts/run.py digest|breaking
        ├─ claude -p --agent news-curator      ← searches the web, follows news-brief.md, returns JSON
        ├─ drops stories already in state/sent.json
        ├─ finds each article's lead image
        └─ sends to Telegram, then saves state/sent.json back to the repo
```

## Files

| File | What it does |
|---|---|
| `news-brief.md` | Your topics, skip list, breaking bar and writing style. **Edit this to change what you get.** |
| `.claude/agents/news-curator.md` | The Claude Code subagent: how it researches and the JSON it must return. |
| `scripts/run.py` | Runs Claude headless, removes repeats, adds images, sends to Telegram. Python standard library only, nothing to install. |
| `.github/workflows/digest.yml` | Morning digest schedule. |
| `.github/workflows/breaking.yml` | Hourly breaking check schedule. |
| `state/sent.json` | Log of stories already sent (last 4 days). Updated automatically. |
| `.env.example` | Template for running it on your Mac. |

---

## Step 1. Create the Telegram bot (5 min)

1. Open Telegram and go to **@BotFather**: https://t.me/BotFather
2. Send `/newbot`. Give it a name (for example `Saad News`) and a username ending in `bot` (for example `saad_news_24_bot`).
3. BotFather replies with a token like `123456789:AAH...`. This is your **TELEGRAM_BOT_TOKEN**. Keep it private.
4. Open your new bot in Telegram and press **Start**, then send it any message (for example `hi`).
5. In your browser open this, with your token pasted in:
   `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates`
6. Find `"chat":{"id":123456789` in the text. That number is your **TELEGRAM_CHAT_ID**.
   If the page shows `"result":[]`, send the bot another message and refresh.

## Step 2. Get your Claude credential (5 min)

Pick **one**:

**Option A: Anthropic API key (pay per use, recommended)**
1. Sign in at https://console.anthropic.com
2. Add credit: https://console.anthropic.com/settings/billing
3. Set a monthly spend limit so it can never surprise you: https://console.anthropic.com/settings/limits
4. Create a key: https://console.anthropic.com/settings/keys → **Create Key**. Copy it (starts with `sk-ant-`). This is your **ANTHROPIC_API_KEY**.

**Option B: your Claude Pro or Max subscription**
1. Install Claude Code first (Step 3.2).
2. In Terminal run `claude setup-token` and follow the login.
3. Copy the token it prints. This is your **CLAUDE_CODE_OAUTH_TOKEN**. Use it in place of the API key everywhere below.
   Usage then counts against your subscription limits, not API credit.

## Step 3. Test on your Mac first (15 min, recommended)

1. **Install Node.js 18 or newer** (LTS): https://nodejs.org/en/download
   Check in Terminal: `node -v`
2. **Install Claude Code** (official guide: https://code.claude.com/docs/en/setup):
   ```bash
   npm install -g @anthropic-ai/claude-code
   claude --version
   ```
3. **Check Python 3** (it comes with Xcode's command line tools): `python3 --version`
4. **Put the project folder somewhere**, for example `~/news-digest`, and go into it:
   ```bash
   cd ~/news-digest
   ```
5. **Add your secrets locally:**
   ```bash
   cp .env.example .env
   open -e .env
   ```
   Fill in the 3 values, save, close. `.env` is in `.gitignore`, so it never gets uploaded.
6. **Dry run** (searches the news and prints the result, sends nothing):
   ```bash
   python3 scripts/run.py digest --dry-run
   ```
   It takes about 3 to 8 minutes. The last log line before the items shows the cost of the run.
7. **Real send** to Telegram:
   ```bash
   python3 scripts/run.py digest
   python3 scripts/run.py breaking
   ```
   `breaking` usually prints `0 new item(s)` and sends nothing. That is correct.
8. **Optional: see the agent inside Claude Code.** Run `claude` in the folder, type `/agents`, and you will see `news-curator`. You can also chat with it, for example: `use the news-curator agent to find today's top 3 AI stories`.

## Step 4. Put it on GitHub (10 min)

1. Create a repository: https://github.com/new
   - Name: `news-digest`
   - **Public or private:** public repos get unlimited free Actions minutes. Private repos on the free plan get 2,000 minutes a month, and the hourly check alone uses roughly 1,500 to 2,500 minutes a month, so private may run out. Your secrets stay hidden either way; only `news-brief.md` and the sent headlines are visible in a public repo.
   - Do **not** tick "Add a README".
2. Upload the folder with Terminal (do not drag and drop in the browser: macOS hides `.github` and `.claude`, so they would be skipped):
   ```bash
   cd ~/news-digest
   git init
   git add .
   git commit -m "News digest agent"
   git branch -M main
   git remote add origin https://github.com/<your-username>/news-digest.git
   git push -u origin main
   ```
   If Git asks you to log in, follow the prompt, or install GitHub Desktop (https://desktop.github.com) and publish the folder from there.
3. **Add the secrets.** In the repo: **Settings → Secrets and variables → Actions → New repository secret**. Add each one, name exactly as shown:

   | Name | Value |
   |---|---|
   | `ANTHROPIC_API_KEY` | from Step 2 option A (or skip and add `CLAUDE_CODE_OAUTH_TOKEN` for option B) |
   | `TELEGRAM_BOT_TOKEN` | from Step 1.3 |
   | `TELEGRAM_CHAT_ID` | from Step 1.6 |

   Official guide: https://docs.github.com/en/actions/security-for-github-actions/security-guides/using-secrets-in-github-actions
4. **Allow the workflow to save the sent log:** **Settings → Actions → General → Workflow permissions →** select **Read and write permissions** → **Save**.

## Step 5. Run it once by hand

1. Open the repo's **Actions** tab.
2. If GitHub asks, click **I understand my workflows, go ahead and enable them**.
3. Click **Morning digest → Run workflow → Run workflow**.
4. Wait for the green tick (about 5 to 10 minutes) and check Telegram.
5. Do the same for **Breaking news check** to confirm it runs without errors.

From now on it runs by itself. If a run fails, GitHub emails you.

---

## Change things

| Want to | Edit |
|---|---|
| Add or remove topics, change the breaking bar, change style | `news-brief.md` |
| Digest time | `cron` in `.github/workflows/digest.yml`. It is in UTC, so Dubai minus 4 hours. Helper: https://crontab.guru |
| Breaking check frequency or hours | `cron` in `.github/workflows/breaking.yml`. `"20 * * * *"` = every hour, 24/7. `"20 2-20/2 * * *"` = every 2 hours |
| Model | Repo **Settings → Secrets and variables → Actions → Variables** → add `NEWS_MODEL` (`sonnet`, `opus` or `haiku`). Default is `sonnet` |
| Cost cap per run | Add a variable or env `MAX_BUDGET_USD`. Defaults: 1.50 for the digest, 0.40 for a breaking check |

## Cost

Exact cost per run: insufficient data to verify before you run it, because it depends on how many searches and pages the agent opens. Each run prints its real cost in the log (`[run] cost: $...`).

The hard caps are: digest ≤ $1.50 per run, breaking ≤ $0.40 per run. Worst case with the default schedule is 1 digest + 19 checks = about $9 a day; real runs should be well below the caps. Check your first day in the console (https://console.anthropic.com/usage) and adjust. The biggest saver is checking breaking news every 2 hours instead of every hour.

## Troubleshooting

| Problem | Fix |
|---|---|
| `set TELEGRAM_CHAT_ID` / `set ANTHROPIC_API_KEY` | A secret is missing or misspelled. Names are case-sensitive. |
| Telegram error `chat not found` | You did not press **Start** on your bot, or the chat ID is wrong. Redo Step 1.4 to 1.6. |
| No image on some items | That site blocks image fetching. The item is sent as text with a link preview instead. |
| `Save sent log` step fails with 403 | Do Step 4.4 (Read and write permissions). |
| Digest arrives at 8:10 or later | GitHub delays scheduled runs at busy times. Move the cron earlier, for example `"30 3 * * *"`. |
| Same story sent twice | The headline and link both changed. The agent also sees the sent list, so this should be rare. Tighten the wording in `news-brief.md` if it repeats. |
| Schedules stopped | GitHub pauses schedules after 60 days without repo activity. The sent-log commits normally keep it active; if paused, re-enable in the Actions tab. |
