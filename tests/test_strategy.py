import numpy as np, pandas as pd
from app.strategy import analyze

def candles(n=300):
    rng=np.random.default_rng(1); close=60000+np.cumsum(rng.normal(20,100,n)); op=close-rng.normal(0,30,n)
    hi=np.maximum(op,close)+rng.uniform(10,80,n); lo=np.minimum(op,close)-rng.uniform(10,80,n)
    return pd.DataFrame({"open":op,"high":hi,"low":lo,"close":close,"volume":rng.uniform(10,100,n)})

def test_analyze_returns_signal():
    d=candles(); s=analyze(d,d,d); assert s.side in {"LONG","SHORT","WAIT"}; assert 0 <= s.score <= 100
