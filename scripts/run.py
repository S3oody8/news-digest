#!/usr/bin/env python3
"""Run the news-curator agent headlessly with `claude -p` and send the result to Telegram.

Usage:
  python3 scripts/run.py digest              # morning digest
  python3 scripts/run.py breaking            # breaking-news check
  python3 scripts/run.py digest --dry-run    # print instead of sending, don't update the sent log

Needs (environment variables or a .env file in the project root):
  CLAUDE_CODE_OAUTH_TOKEN   (from `claude setup-token`; ANTHROPIC_API_KEY is never used)
  TELEGRAM_BOT_TOKEN
  TELEGRAM_CHAT_ID
Optional:
  NEWS_MODEL          default "sonnet"
  MAX_BUDGET_USD      default 1.50 for digest, 0.40 for breaking
"""
import argparse
import datetime as dt
import html
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE_FILE = ROOT / "state" / "sent.json"
DUBAI = dt.timezone(dt.timedelta(hours=4))
KEEP_DAYS = 4
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
DEFAULT_BUDGET = {"digest": "1.50", "breaking": "0.40"}


# ---------- setup ----------

def load_dotenv():
    env = ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


def now_dubai():
    return dt.datetime.now(DUBAI)


# ---------- sent log (dedup) ----------

def norm_url(url):
    p = urllib.parse.urlsplit(url.strip())
    host = p.netloc.lower().removeprefix("www.")
    return f"{host}{p.path.rstrip('/')}"


def norm_headline(text):
    return re.sub(r"[^a-z0-9 ]", "", text.lower()).strip()


def load_state():
    try:
        return json.loads(STATE_FILE.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {"sent": []}


def save_state(state):
    cutoff = time.time() - KEEP_DAYS * 86400
    state["sent"] = [s for s in state["sent"] if s.get("ts", 0) >= cutoff]
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n")


def already_sent(state, item):
    u, h = norm_url(item["url"]), norm_headline(item["headline"])
    return any(s.get("url") == u or s.get("headline") == h for s in state["sent"])


def mark_sent(state, item, mode):
    state["sent"].append({
        "ts": int(time.time()),
        "mode": mode,
        "url": norm_url(item["url"]),
        "headline": norm_headline(item["headline"]),
        "title": item["headline"],
    })


# ---------- Claude ----------

TASKS = {
    "digest": (
        "Build the MORNING DIGEST: the 10 to 12 most important stories from the last 24 hours "
        "across Saad's topics, following the 'Morning digest' rules in news-brief.md."
    ),
    "breaking": (
        "Run a BREAKING CHECK: look only for stories first reported in the last 90 minutes that clear "
        "ALL THREE tests of the 'Breaking alert bar' in news-brief.md. Return an empty items list if "
        "nothing qualifies, which is the normal result."
    ),
}


def build_prompt(mode, state):
    titles = [s["title"] for s in state["sent"]][-120:]
    recent = "\n".join(f"- {t}" for t in titles) or "- (none yet)"
    return (
        f"Mode: {mode}\n"
        f"Current time: {now_dubai():%A %d %B %Y, %H:%M} Dubai time (UTC+4).\n\n"
        f"{TASKS[mode]}\n\n"
        "Already sent in the last few days (do not repeat these stories unless there is a major new "
        f"development, and then the headline must say what is new):\n{recent}\n\n"
        "Reply with the JSON object only, as defined in your instructions."
    )


def run_claude(mode, state):
    model = os.environ.get("NEWS_MODEL", "sonnet")
    budget = os.environ.get("MAX_BUDGET_USD", DEFAULT_BUDGET[mode])
    cmd = [
        "claude", "-p", build_prompt(mode, state),
        "--agent", "news-curator",
        "--model", model,
        "--output-format", "json",
        "--max-budget-usd", budget,
        "--allowedTools", "Read,WebSearch,WebFetch",
    ]
    print(f"[run] claude -p --agent news-curator --model {model} (budget ${budget})", file=sys.stderr)
    # Always authenticate with the Claude subscription token, never an API key.
    env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
    proc = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True, timeout=1500)
    if proc.returncode != 0:
        sys.exit(f"[error] claude exited {proc.returncode}\n{proc.stderr[-2000:]}\n{proc.stdout[-2000:]}")
    try:
        envelope = json.loads(proc.stdout)
    except json.JSONDecodeError:
        sys.exit(f"[error] claude did not return JSON:\n{proc.stdout[-2000:]}")
    cost = envelope.get("total_cost_usd")
    if cost is not None:
        print(f"[run] cost: ${cost:.3f}", file=sys.stderr)
    if envelope.get("modelUsage"):
        print(f"[run] models used: {', '.join(envelope['modelUsage'])}", file=sys.stderr)
    if envelope.get("is_error"):
        sys.exit(f"[error] claude reported an error: {envelope.get('result') or envelope}")
    return parse_items(envelope.get("result", ""))


def parse_items(text):
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        sys.exit(f"[error] no JSON object in agent reply:\n{text[:2000]}")
    data = json.loads(text[start:end + 1])
    items = []
    for it in data.get("items", []):
        summary = it.get("summary", [])
        if isinstance(summary, str):
            summary = [s for s in summary.split("\n") if s.strip()]
        url = str(it.get("url", "")).strip()
        headline = str(it.get("headline", "")).strip()
        if not headline or not url.startswith("http"):
            print(f"[skip] invalid item: {it}", file=sys.stderr)
            continue
        items.append({
            "emoji": str(it.get("emoji", "")).strip(),
            "section": str(it.get("section", "")).strip(),
            "headline": headline,
            "summary": [str(s).strip() for s in summary][:3],
            "url": url,
            "source": str(it.get("source", "")).strip() or urllib.parse.urlsplit(url).netloc,
            "image_url": str(it.get("image_url", "")).strip(),
        })
    return items


# ---------- images ----------

META_RE = re.compile(r"<meta\b[^>]*>", re.I)


def find_image(article_url):
    """Return the article's og:image / twitter:image, or ''."""
    try:
        req = urllib.request.Request(article_url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=12) as r:
            page = r.read(600_000).decode("utf-8", "ignore")
    except Exception as e:
        print(f"[img] could not open {article_url}: {e}", file=sys.stderr)
        return ""
    for wanted in ("og:image", "twitter:image", "og:image:url"):
        for tag in META_RE.findall(page):
            if re.search(rf'(?:property|name)\s*=\s*["\']{re.escape(wanted)}["\']', tag, re.I):
                m = re.search(r'content\s*=\s*["\']([^"\']+)["\']', tag, re.I)
                if m:
                    return urllib.parse.urljoin(article_url, html.unescape(m.group(1)))
    return ""


# ---------- Telegram ----------

def tg(method, payload):
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    data = urllib.parse.urlencode(payload).encode()
    req = urllib.request.Request(f"https://api.telegram.org/bot{token}/{method}", data=data)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return json.loads(e.read() or b"{}") or {"ok": False, "description": str(e)}


def caption(item, breaking=False):
    e = html.escape
    tag = "🚨 <b>BREAKING</b>\n" if breaking else ""
    lines = "\n".join(f"• {e(s)}" for s in item["summary"])
    return (
        f"{tag}{e(item['emoji'])} <b>{e(item['headline'])}</b>\n\n"
        f"{lines}\n\n"
        f'<a href="{e(item["url"], quote=True)}">{e(item["source"])}</a>'
    )[:1024]


def send_item(item, breaking, silent):
    chat = os.environ["TELEGRAM_CHAT_ID"]
    text = caption(item, breaking)
    common = {"chat_id": chat, "parse_mode": "HTML", "disable_notification": str(silent).lower()}
    for img in [item["image_url"], find_image(item["url"])]:
        if not img:
            continue
        res = tg("sendPhoto", {**common, "photo": img, "caption": text})
        if res.get("ok"):
            return True
        print(f"[tg] photo failed ({res.get('description')}), trying next option", file=sys.stderr)
    res = tg("sendMessage", {**common, "text": text})
    if not res.get("ok"):
        print(f"[tg] message failed: {res.get('description')}", file=sys.stderr)
    return bool(res.get("ok"))


def preview(item, breaking):
    img = item["image_url"] or find_image(item["url"])
    print("\n" + html.unescape(re.sub(r"<[^>]+>", "", caption(item, breaking))))
    print(f"  image: {img or '(none, will send as text)'}")


# ---------- main ----------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["digest", "breaking"])
    ap.add_argument("--dry-run", action="store_true", help="print instead of sending")
    args = ap.parse_args()

    load_dotenv()
    if not os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"):
        sys.exit("[error] set CLAUDE_CODE_OAUTH_TOKEN (from `claude setup-token`)")
    if not args.dry_run:
        for var in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"):
            if not os.environ.get(var):
                sys.exit(f"[error] set {var}")

    state = load_state()
    items = [i for i in run_claude(args.mode, state) if not already_sent(state, i)]
    breaking = args.mode == "breaking"
    if breaking:
        items = items[:2]
    print(f"[run] {len(items)} new item(s)", file=sys.stderr)

    if not items:
        return  # nothing to send (normal for breaking checks)

    if args.dry_run:
        for item in items:
            preview(item, breaking)
        return

    if not breaking:
        header = f"🌍 <b>What happened in the last 24 hours</b>\n{now_dubai():%A %d %B}"
        tg("sendMessage", {"chat_id": os.environ["TELEGRAM_CHAT_ID"], "text": header, "parse_mode": "HTML"})

    sent = 0
    for item in items:
        # Digest: only the header buzzes, items arrive silently. Breaking: every alert buzzes.
        if send_item(item, breaking, silent=not breaking):
            mark_sent(state, item, args.mode)
            save_state(state)
            sent += 1
        time.sleep(1.2)  # stay under Telegram's per-chat rate limit
    print(f"[run] sent {sent}/{len(items)}", file=sys.stderr)
    if sent == 0:
        sys.exit("[error] nothing could be delivered to Telegram")


if __name__ == "__main__":
    main()
