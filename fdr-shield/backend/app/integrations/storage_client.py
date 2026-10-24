import boto3
import logging
import time
import base64
import hashlib
import hmac
from pathlib import Path
from datetime import datetime, timezone
from app.core.config import get_settings

logger=logging.getLogger(__name__)

def _client():
 s=get_settings();return boto3.client('s3',endpoint_url=s.s3_endpoint,aws_access_key_id=s.s3_access_key,aws_secret_access_key=s.s3_secret_key)
def ensure_bucket()->None:
 s=get_settings()
 if s.storage_backend == 'local':
  Path(s.storage_local_path).mkdir(parents=True, exist_ok=True)
  return
 c=_client()
 last_error=None
 for attempt in range(6):
  try:
   c.head_bucket(Bucket=s.s3_bucket)
   return
  except Exception as exc:
   last_error=exc
   try:
    c.create_bucket(Bucket=s.s3_bucket)
    return
   except Exception as create_error:
    last_error=create_error
    if attempt<5:
     logger.warning('MinIO not ready (attempt %s/6); retrying',attempt+1)
     time.sleep(min(1.0+attempt,4.0))
 if last_error: raise RuntimeError('Could not reach MinIO or create the document bucket after retries') from last_error
def put(key:str,data:bytes,content_type:str)->None:
 if get_settings().storage_backend == 'local':
  path=(Path(get_settings().storage_local_path)/key).resolve();root=Path(get_settings().storage_local_path).resolve()
  if root not in path.parents: raise ValueError('Invalid storage key')
  path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data);return
 _client().put_object(Bucket=get_settings().s3_bucket,Key=key,Body=data,ContentType=content_type)
def get(key:str)->bytes:
 if get_settings().storage_backend == 'local':
  path=(Path(get_settings().storage_local_path)/key).resolve();root=Path(get_settings().storage_local_path).resolve()
  if root not in path.parents: raise ValueError('Invalid storage key')
  return path.read_bytes()
 return _client().get_object(Bucket=get_settings().s3_bucket,Key=key)['Body'].read()
def presign(key:str,expires:int=300)->str:
 if get_settings().storage_backend == 'local':
  expiry=int(datetime.now(timezone.utc).timestamp())+expires
  raw=base64.urlsafe_b64encode(key.encode()).decode().rstrip('=');message=f'{raw}:{expiry}'
  secret=get_settings().jwt_secret.encode();signature=hmac.new(secret,message.encode(),hashlib.sha256).hexdigest()
  return f'http://localhost:8000/api/v1/documents/local/{raw}.{expiry}.{signature}'
 return _client().generate_presigned_url('get_object',Params={'Bucket':get_settings().s3_bucket,'Key':key},ExpiresIn=expires)

def read_local_token(token:str)->bytes:
 try:
  raw,expires,signature=token.rsplit('.',2);message=f'{raw}:{expires}'
  expected=hmac.new(get_settings().jwt_secret.encode(),message.encode(),hashlib.sha256).hexdigest()
  if not hmac.compare_digest(signature,expected) or int(expires)<int(datetime.now(timezone.utc).timestamp()): raise ValueError
  key=base64.urlsafe_b64decode(raw+'='*((4-len(raw)%4)%4)).decode()
  return get(key)
 except Exception as exc: raise ValueError('Invalid or expired local document link') from exc
