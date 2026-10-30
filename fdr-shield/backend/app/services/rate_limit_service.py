"""Shared Redis-backed abuse limits for expensive AI/OCR/command endpoints.

When Redis is temporarily unavailable a bounded per-process sliding window remains
active and reports degraded operation through logs; deployments should use Redis.
"""
from collections import deque
import asyncio
import hashlib
import logging
import threading
import time
from app.core.config import get_settings
from app.core.exceptions import RateLimitError

logger=logging.getLogger(__name__)
_lock=threading.Lock()
_local:dict[str,deque[float]]={}
_SCRIPT="""
local n=redis.call('INCR',KEYS[1])
if n==1 then redis.call('EXPIRE',KEYS[1],ARGV[1]) end
return n
"""


async def enforce_rate_limit(scope: str, identity: str, limit: int, window_seconds: int=60) -> None:
    digest=hashlib.sha256(identity.encode('utf-8')).hexdigest()[:24]
    key=f'fdr-rate:{scope}:{digest}'
    try:
        from redis import Redis
        redis=Redis.from_url(get_settings().redis_url,decode_responses=True,socket_connect_timeout=.25,socket_timeout=.25)
        count=await asyncio.to_thread(redis.eval,_SCRIPT,1,key,window_seconds)
        await asyncio.to_thread(redis.close)
        if int(count)>limit: raise RateLimitError('Too many requests. Please try again shortly.')
        return
    except RateLimitError: raise
    except Exception:
        logger.warning('Redis rate limiter unavailable; applying per-worker fallback',extra={'scope':scope})
    now=time.monotonic()
    with _lock:
        bucket=_local.setdefault(key,deque())
        while bucket and bucket[0]<=now-window_seconds: bucket.popleft()
        if len(bucket)>=limit: raise RateLimitError('Too many requests. Please try again shortly.')
        bucket.append(now)
        if len(_local)>10000:
            for candidate in list(_local)[:1000]:
                if not _local[candidate] or _local[candidate][-1]<=now-window_seconds: _local.pop(candidate,None)
