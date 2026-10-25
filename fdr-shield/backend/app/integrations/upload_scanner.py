"""Optional ClamAV daemon scanner; uploads fail closed if configured scanner is down."""
from __future__ import annotations
import asyncio
import socket
import struct
from app.core.config import get_settings
from app.core.exceptions import InvalidStateTransition


def _clamav_instream(data: bytes, host: str, port: int, timeout: float) -> str:
    chunks=[]
    with socket.create_connection((host,port),timeout=timeout) as connection:
        connection.settimeout(timeout)
        connection.sendall(b'zINSTREAM\0')
        for start in range(0,len(data),64*1024):
            chunk=data[start:start+64*1024]
            connection.sendall(struct.pack('!I',len(chunk))+chunk)
        connection.sendall(struct.pack('!I',0))
        while True:
            packet=connection.recv(4096)
            if not packet: break
            chunks.append(packet)
            if b'\0' in packet or sum(map(len,chunks))>8192: break
    return b''.join(chunks).decode('utf-8','replace').strip('\0\r\n ')


async def scan_upload(data: bytes) -> dict:
    settings=get_settings()
    if not settings.clamav_host:
        return {'scanned':False,'engine':'not_configured'}
    try:
        response=await asyncio.to_thread(_clamav_instream,data,settings.clamav_host,
            settings.clamav_port,settings.clamav_timeout_seconds)
    except Exception as exc:
        raise InvalidStateTransition('UPLOAD_SCANNER_UNAVAILABLE: configured malware scanner did not respond; upload was not stored.') from exc
    if 'FOUND' in response.upper():
        raise InvalidStateTransition('MALWARE_DETECTED: upload was rejected by the configured malware scanner.')
    if 'OK' not in response.upper():
        raise InvalidStateTransition('UPLOAD_SCANNER_ERROR: malware scanner returned an invalid response; upload was not stored.')
    return {'scanned':True,'engine':'clamav'}
