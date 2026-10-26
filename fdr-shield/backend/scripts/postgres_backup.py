"""Create a private PostgreSQL custom-format backup or verify a restore to a disposable DB.

No database password is placed on the command line. Retention, encryption-at-rest,
offsite replication and the disposable restore database must be configured by the
deployment owner; this helper never deletes old backups.
"""
from __future__ import annotations
import argparse
import hashlib
import os
from pathlib import Path
import subprocess
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from sqlalchemy.engine import make_url

from app.core.config import get_settings


def _connection_args(url_text: str) -> tuple[list[str], dict]:
    url=make_url(url_text)
    if url.get_backend_name()!='postgresql':
        raise ValueError('PostgreSQL backup utility requires a PostgreSQL DATABASE_URL.')
    args=['--host',url.host or 'localhost','--port',str(url.port or 5432),
        '--username',url.username or '', '--dbname',url.database or '']
    env=os.environ.copy()
    if url.password is not None: env['PGPASSWORD']=url.password
    env['PGSSLMODE']=env.get('PGSSLMODE','prefer')
    return args,env


def _sha256(path: Path) -> str:
    digest=hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''): digest.update(chunk)
    return digest.hexdigest()


def backup(path: Path) -> dict:
    path=path.resolve()
    path.parent.mkdir(parents=True,exist_ok=True)
    args,env=_connection_args(get_settings().database_url)
    # Exclusive creation and restrictive permissions avoid overwriting a prior backup.
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    try:
        with os.fdopen(fd,'wb') as output:
            subprocess.run(['pg_dump','--format=custom','--no-owner','--no-acl',*args],
                stdout=output,stderr=subprocess.PIPE,check=True,env=env)
    except Exception:
        path.unlink(missing_ok=True)
        raise
    digest=_sha256(path)
    checksum=path.with_suffix(path.suffix+'.sha256')
    checksum.write_text(f'{digest}  {path.name}\n',encoding='ascii')
    try: os.chmod(checksum,0o600)
    except OSError: pass
    return {'backup':str(path),'sha256':digest,'bytes':path.stat().st_size}


def verify_restore(path: Path, target_url: str) -> dict:
    path=path.resolve()
    if not path.is_file(): raise ValueError('Backup archive does not exist.')
    checksum=path.with_suffix(path.suffix+'.sha256')
    if not checksum.is_file() or checksum.read_text(encoding='ascii').split()[0]!=_sha256(path):
        raise ValueError('Backup checksum is missing or invalid.')
    source=make_url(get_settings().database_url);target=make_url(target_url)
    if (source.host,source.port,source.database)==(target.host,target.port,target.database):
        raise ValueError('Restore target must be a different, explicitly disposable database.')
    args,env=_connection_args(target_url)
    subprocess.run(['pg_restore','--exit-on-error','--clean','--if-exists','--no-owner','--no-acl',
        *args,str(path)],check=True,env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    import psycopg2
    conn=psycopg2.connect(host=target.host or 'localhost',port=target.port or 5432,
        user=target.username,database=target.database,password=target.password)
    try:
        with conn.cursor() as cursor:
            cursor.execute('SELECT version_num FROM alembic_version')
            migration=cursor.fetchone()[0]
            cursor.execute('SELECT count(*) FROM audit_logs')
            audit_count=cursor.fetchone()[0]
            cursor.execute('SELECT count(*) FROM fdrs')
            fdr_count=cursor.fetchone()[0]
    finally: conn.close()
    return {'restored':True,'migration':migration,'audit_rows':audit_count,'fdr_rows':fdr_count,
        'backup_sha256':_sha256(path),'target_database':target.database}


def main() -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    commands=parser.add_subparsers(dest='command',required=True)
    create=commands.add_parser('backup');create.add_argument('path',type=Path)
    restore=commands.add_parser('verify-restore');restore.add_argument('path',type=Path)
    restore.add_argument('--restore-url-env',default='RESTORE_DATABASE_URL',
        help='Environment variable containing the disposable target URL (never put credentials in argv).')
    args=parser.parse_args()
    try:
        if args.command=='backup': result=backup(args.path)
        else:
            target_url=os.environ.get(args.restore_url_env)
            if not target_url: raise ValueError(f'{args.restore_url_env} environment variable is required.')
            result=verify_restore(args.path,target_url)
        import json
        print(json.dumps(result,indent=2))
        return 0
    except Exception as exc:
        # Avoid printing exception text from DB clients, which can contain connection info.
        print(f'Backup operation failed ({type(exc).__name__}). Check database/tool availability and deployment runbook.',file=sys.stderr)
        return 1


if __name__=='__main__': raise SystemExit(main())
