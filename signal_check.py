"""Daily trend-rule check for BTC-EUR. DRY RUN: reads public candles only, never places orders."""
import csv, os, time
import numpy as np
import pandas as pd
import requests

URL = "https://api.bitvavo.com/v2/BTC-EUR/candles"
LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "signal_log.csv")


def fetch_daily():
    r = requests.get(URL, params={"interval": "1d", "limit": 1440}, timeout=30)
    r.raise_for_status()
    df = pd.DataFrame(r.json(), columns=["time", "open", "high", "low", "close", "volume"])
    df = df.astype({"time": "int64", "close": float}).sort_values("time").reset_index(drop=True)
    df["dt"] = pd.to_datetime(df["time"], unit="ms", utc=True)
    today = pd.Timestamp.now(tz="UTC").normalize()
    return df[df["dt"] < today].reset_index(drop=True)   # closed candles only


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


def main():
    df = fetch_daily()
    c = df["close"]
    rules = {
        "SMA100 +-3% band": band_state(c.values, c.rolling(100).mean().values),
        "close > EMA100": (c > c.ewm(span=100, adjust=False).mean()).values,
        "close > SMA150": (c > c.rolling(150).mean()).values,
    }
    last = df.iloc[-1]
    print(f"BTC-EUR daily check (DRY RUN, no orders). Last closed candle: {last['dt'].date()}  close EUR {last['close']:,.0f}")
    print(f"{'rule':20s} {'signal':8s} {'since':12s} {'days':>5s}  detail")
    row = {"checked_utc": pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%d %H:%M"), "candle": str(last["dt"].date()),
           "close": round(float(last["close"]), 2)}
    sma100, ema100, sma150 = c.rolling(100).mean().iloc[-1], c.ewm(span=100, adjust=False).mean().iloc[-1], c.rolling(150).mean().iloc[-1]
    detail = {
        "SMA100 +-3% band": f"SMA100 {sma100:,.0f}; enter above {sma100*1.03:,.0f}, exit below {sma100*0.97:,.0f}",
        "close > EMA100": f"EMA100 {ema100:,.0f}",
        "close > SMA150": f"SMA150 {sma150:,.0f}",
    }
    for name, st in rules.items():
        s = np.asarray(st, bool)
        flips = np.where(s[1:] != s[:-1])[0]
        since = df["dt"].iloc[flips[-1] + 1].date() if len(flips) else df["dt"].iloc[0].date()
        days = (last["dt"].date() - since).days
        sig = "HOLD BTC" if s[-1] else "IN EUR"
        print(f"{name:20s} {sig:8s} {str(since):12s} {days:5d}  {detail[name]}")
        row[name] = sig
    new = not os.path.exists(LOG)
    with open(LOG, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(row.keys()))
        if new:
            w.writeheader()
        w.writerow(row)
    print(f"\nLogged to {LOG}. Backtested rules only: not advice, and no order is sent.")


if __name__ == "__main__":
    main()
