import json
from functools import lru_cache
from pathlib import Path
import asyncio

@lru_cache
def load_seed()->dict:
    path=Path(__file__).parent/'data'/'seed_fdrs.json'
    data=json.loads(path.read_text(encoding='utf-8'))
    return {(bank.lower(),r['fdr_number']):r for bank,rows in data.items() for r in rows}
def lookup(bank:str,fdr_number:str)->dict|None: return load_seed().get((bank.lower(),fdr_number))
async def simulate_latency()->None: await asyncio.sleep(0)
