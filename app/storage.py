from __future__ import annotations
import csv, os
from dataclasses import asdict
from .strategy import Signal

FIELDS=["timestamp","side","score","price","entry","stop","target","reasons"]
def save(signal: Signal, path: str):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    exists=os.path.exists(path)
    with open(path,"a",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=FIELDS)
        if not exists: w.writeheader()
        row=asdict(signal); row["reasons"]=" | ".join(signal.reasons); w.writerow(row)
