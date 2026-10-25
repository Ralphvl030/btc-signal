"""Daily BTC-EUR trend-rule check. Reads public Bitvavo candles only. Never places orders.

python signal_check.py              log, update state, push a notification on a flip (needs NTFY_TOPIC)
python signal_check.py --no-notify  preview only: rebuilds the status page, writes no state or log, sends nothing
"""
import csv
import json
import os
import sys
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(HERE, "signal_state.json")
LOG = os.path.join(HERE, "signal_log.csv")
PAGE = os.path.join(HERE, "docs", "index.html")
URL = "https://api.bitvavo.com/v2/BTC-EUR/candles"
PREVIEW = "--no-notify" in sys.argv
LABELS = {"SMA100 +-3% band": "SMA100 ±3% band", "close>EMA100": "Price > EMA100", "close>SMA150": "Price > SMA150"}


def fetch_daily():
    r = requests.get(URL, params={"interval": "1d", "limit": 1440}, timeout=30)
    r.raise_for_status()
    df = pd.DataFrame(r.json(), columns=["time", "open", "high", "low", "close", "volume"])
    df = df.astype({"time": "int64", "close": float}).sort_values("time").reset_index(drop=True)
    df["dt"] = pd.to_datetime(df["time"], unit="ms", utc=True)
    today = pd.Timestamp.now(tz="UTC").normalize()
    return df[df["dt"] < today].reset_index(drop=True)


def band_state(c, sm, up=1.03, dn=0.97):
    cur, out = False, []
    for x, m in zip(c, sm):
        if not np.isnan(m):
            if not cur and x > m * up:
                cur = True
            elif cur and x < m * dn:
                cur = False
        out.append(cur)
    return np.array(out)


def evaluate(df):
    c = df["close"]
    sma100, ema100, sma150 = c.rolling(100).mean(), c.ewm(span=100, adjust=False).mean(), c.rolling(150).mean()
    series = {"SMA100 +-3% band": band_state(c.values, sma100.values), "close>EMA100": (c > ema100).values, "close>SMA150": (c > sma150).values}
    detail = {"SMA100 +-3% band": f"SMA100 is €{sma100.iloc[-1]:,.0f}. Holds BTC above €{sma100.iloc[-1] * 1.03:,.0f}, goes to EUR below €{sma100.iloc[-1] * 0.97:,.0f}.",
              "close>EMA100": f"EMA100 is €{ema100.iloc[-1]:,.0f}. Holds BTC while the close is above it.",
              "close>SMA150": f"SMA150 is €{sma150.iloc[-1]:,.0f}. Holds BTC while the close is above it."}
    last = df["dt"].iloc[-1]
    rules = {}
    for name, s in series.items():
        s = np.asarray(s, bool)
        flips = np.where(s[1:] != s[:-1])[0]
        since = df["dt"].iloc[flips[-1] + 1] if len(flips) else df["dt"].iloc[0]
        rules[name] = {"hold": bool(s[-1]), "since": str(since.date()), "days": int((last - since).days), "detail": detail[name]}
    return rules


def notify(title, message, priority=3, tags=""):
    topic = os.environ.get("NTFY_TOPIC", "").strip()
    if not topic:
        p = os.path.join(HERE, "..", "ntfy_topic.txt")
        topic = open(p).read().strip() if os.path.exists(p) else ""
    if not topic or PREVIEW:
        print(f"[notification not sent] {title}: {message}")
        return False
    try:
        r = requests.post(f"https://ntfy.sh/{topic}", data=message.encode("utf-8"),
                          headers={"Title": title, "Priority": str(priority), "Tags": tags}, timeout=20)
        r.raise_for_status()
        print("notification sent:", title)
        return True
    except Exception as e:
        print("notification FAILED:", e)
        return False


def write_page(rules, candle, close, updated):
    holding = sum(r["hold"] for r in rules.values())
    cards = ""
    for name, r in rules.items():
        cls, txt = ("hold", "HOLD BTC") if r["hold"] else ("eur", "IN EUR")
        d = datetime.strptime(r["since"], "%Y-%m-%d").strftime("%d %b %Y")
        cards += f'<section class="card"><h2>{LABELS[name]}</h2><div class="state {cls}">{txt}</div><div class="since">since {d} · {r["days"]} days</div><p>{r["detail"]}</p></section>'
    html = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="theme-color" content="#0c1019"><title>BTC Signal</title>
<style>
:root{{--bg:#f2f4f8;--surface:#fff;--line:#d5dbe6;--ink:#141a2a;--muted:#5b6478;--good:#0f8f5f;--warn:#a86a00;--good-bg:#e3f4ec;--warn-bg:#fbf0d9}}
@media (prefers-color-scheme:dark){{:root{{--bg:#0c1019;--surface:#131926;--line:#252f44;--ink:#e7ebf5;--muted:#8b95ab;--good:#2fd08f;--warn:#f2b043;--good-bg:#0f2a21;--warn-bg:#2d2411}}}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font-family:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;padding:20px 16px 32px}}
.wrap{{max-width:560px;margin:0 auto;display:flex;flex-direction:column;gap:14px}}
h1{{font-size:1.3rem;margin:0}}.top{{color:var(--muted);font-size:.9rem;line-height:1.5}}
.card{{background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:16px 18px}}
.card h2{{margin:0 0 8px;font-size:.78rem;letter-spacing:.09em;text-transform:uppercase;color:var(--muted);font-weight:600}}
.state{{font-size:1.9rem;font-weight:700;display:inline-block;padding:4px 12px;border-radius:8px}}
.state.hold{{color:var(--good);background:var(--good-bg)}}.state.eur{{color:var(--warn);background:var(--warn-bg)}}
.since{{margin-top:8px;font-size:.9rem;color:var(--muted)}}.card p{{margin:10px 0 0;font-size:.88rem;line-height:1.5}}
.foot{{color:var(--muted);font-size:.78rem;line-height:1.6}}
</style></head><body><div class="wrap">
<h1>BTC-EUR signal</h1>
<div class="top"><b>{holding} of {len(rules)}</b> rules say hold BTC.<br>Last closed candle {datetime.strptime(candle, "%Y-%m-%d").strftime("%d %b %Y")}, close €{close:,.0f}.</div>
{cards}
<div class="foot">Updated {updated} UTC. Daily trend rules backtested on Bitvavo BTC-EUR data. Not advice. This page only shows signals; no orders are placed.</div>
</div></body></html>"""
    os.makedirs(os.path.dirname(PAGE), exist_ok=True)
    with open(PAGE, "w", encoding="utf-8", newline="\n") as f:
        f.write(html)


def main():
    df = fetch_daily()
    rules = evaluate(df)
    last = df.iloc[-1]
    candle, close = str(last["dt"].date()), float(last["close"])
    now = datetime.now(timezone.utc)
    updated = now.strftime("%Y-%m-%d %H:%M")
    prev = json.load(open(STATE)) if os.path.exists(STATE) else None

    print(f"BTC-EUR check. Last closed candle {candle}, close EUR {close:,.0f}")
    for name, r in rules.items():
        print(f"  {LABELS[name]:22s} {'HOLD BTC' if r['hold'] else 'IN EUR':9s} since {r['since']} ({r['days']} days)")

    flips = [n for n, r in rules.items() if prev and n in prev["rules"] and prev["rules"][n]["hold"] != r["hold"]]
    hb = prev.get("last_heartbeat") if prev else None
    n_hold = sum(r["hold"] for r in rules.values())
    body = "\n".join(f"{LABELS[n]}: {'HOLD BTC' if r['hold'] else 'IN EUR'} ({r['days']} days)" for n, r in rules.items())
    tail = f"\nClose EUR {close:,.0f} on {datetime.strptime(candle, '%Y-%m-%d').strftime('%d %b %Y')}. Backtested rules, not advice. No order was sent."
    if flips:
        sent = notify("BTC rule change", "Changed: " + ", ".join(LABELS[n] for n in flips) + "\n" + body + tail, 4, "rotating_light")
    elif prev is None:
        sent = notify("BTC signal monitoring started", body + tail, 2, "white_check_mark")
    else:
        sent = notify(f"BTC daily: {n_hold} of {len(rules)} rules hold BTC", "No change.\n" + body + tail, 2, "chart_with_upwards_trend")
    if sent:
        hb = now.isoformat()

    write_page(rules, candle, close, updated)
    if PREVIEW:
        print("preview only: status page rebuilt, no state or log written")
        return
    with open(STATE, "w", encoding="utf-8") as f:
        json.dump({"rules": {n: {"hold": r["hold"], "since": r["since"]} for n, r in rules.items()}, "last_heartbeat": hb,
                   "candle": candle, "updated": updated}, f, indent=1)
    new = not os.path.exists(LOG)
    with open(LOG, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["checked_utc", "candle", "close_eur"] + list(rules.keys()))
        w.writerow([updated, candle, round(close, 2)] + ["HOLD BTC" if r["hold"] else "IN EUR" for r in rules.values()])


if __name__ == "__main__":
    main()
