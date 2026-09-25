from __future__ import annotations
import numpy as np
import pandas as pd

def ema(s, n): return s.ewm(span=n, adjust=False).mean()

def rsi(s, n=14):
    d = s.diff()
    gain = d.clip(lower=0).ewm(alpha=1/n, adjust=False).mean()
    loss = (-d.clip(upper=0)).ewm(alpha=1/n, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    return (100 - 100/(1+rs)).fillna(50)

def atr(df, n=14):
    prev = df.close.shift(1)
    tr = pd.concat([(df.high-df.low), (df.high-prev).abs(), (df.low-prev).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1/n, adjust=False).mean()

def enrich(df):
    x = df.copy()
    x["ema21"] = ema(x.close, 21)
    x["ema50"] = ema(x.close, 50)
    x["rsi"] = rsi(x.close)
    x["atr"] = atr(x)
    x["vol_ma20"] = x.volume.rolling(20).mean()
    x["vol_ratio"] = x.volume / x.vol_ma20.replace(0, np.nan)
    x["hh20"] = x.high.shift(1).rolling(20).max()
    x["ll20"] = x.low.shift(1).rolling(20).min()
    return x
