"""Account-free TCP fault laboratory for the application's transfer lifecycle.

Uses real loopback sockets, paced chunks and a Telethon-shaped adapter. This tests
our transfer/storage/recovery boundaries, not MTProto or Telegram's infrastructure.
No credentials, sessions, public addresses or global network settings are used.
"""
import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import struct
import sys
import tempfile
import time
from types import SimpleNamespace as NS
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from telethon import types
from tg_ascii.backend import TelegramBackend
from tg_ascii.recovery import Recovery

CHUNK=4096
PAYLOAD=bytes(range(256))*512


class Lab:
    def __init__(self):
        self.plans={};self.handlers=set();self.connections=0;self.downloads=0
        self.uploads=[];self.active=0;self.peak=0;self.changed=asyncio.Event()
        self.control_connections=0;self.control_probes=0

    async def __aenter__(self):
        self.server=await asyncio.start_server(self.accept,'127.0.0.1',0,limit=2*CHUNK)
        self.port=self.server.sockets[0].getsockname()[1]
        return self

    async def __aexit__(self,*_):
        self.server.close();await self.server.wait_closed()
        tasks=list(self.handlers)
        for task in tasks:task.cancel()
        await asyncio.gather(*tasks,return_exceptions=True)
        assert not self.handlers,'server handlers leaked'

    def document(self,number=1,**plan):
        self.plans[number]=plan
        return types.Document(number,1,b'',datetime.now(timezone.utc),'application/octet-stream',len(PAYLOAD),1,[])

    async def wait_connections(self,number):
        async with asyncio.timeout(3):
            while self.connections<number:
                self.changed.clear()
                if self.connections<number:await self.changed.wait()

    async def accept(self,reader,writer):
        task=asyncio.current_task();self.handlers.add(task)
        self.connections+=1;self.active+=1;self.peak=max(self.peak,self.active);self.changed.set()
        try:
            operation=await reader.readexactly(1)
            if operation==b'R':
                self.control_connections+=1
                if self.control_connections==1:
                    await reader.read()  # Broken first connection: no ping response until client closes.
                    return
                while await reader.read(1):
                    self.control_probes+=1;await asyncio.sleep(.02)
                    writer.write(b'S');await writer.drain()
                return
            number=struct.unpack('!I',await reader.readexactly(4))[0];plan=self.plans[number]
            await asyncio.sleep(plan.get('latency',0))
            if operation==b'D':
                self.downloads+=1
                sent=0
                for offset in range(0,len(PAYLOAD),CHUNK):
                    chunk=PAYLOAD[offset:offset+CHUNK]
                    await asyncio.sleep(len(chunk)/plan.get('rate',512*1024))
                    writer.write(chunk);await writer.drain();sent+=len(chunk)
                    if plan.get('cut') and sent>=plan['cut']:return
                    if plan.get('stall'):
                        await reader.read();return
            elif operation==b'U':
                length=struct.unpack('!Q',await reader.readexactly(8))[0];received=bytearray()
                while len(received)<length:
                    chunk=await reader.readexactly(min(CHUNK,length-len(received)))
                    await asyncio.sleep(len(chunk)/plan.get('rate',512*1024))
                    received.extend(chunk);writer.write(b'A');await writer.drain()
                self.uploads.append(bytes(received))
                if not plan.get('ambiguous'):
                    writer.write(b'OK');await writer.drain()
            else:raise ValueError('Unknown local test operation')
        except (ConnectionError,asyncio.IncompleteReadError):pass
        finally:
            writer.close()
            try:
                try:await writer.wait_closed()
                except (ConnectionError,OSError):pass
            finally:
                self.active-=1;self.handlers.discard(task)


class SocketClient:
    def __init__(self,lab):self.lab=lab;self.writers=set();self.streams=[];self.send_calls=0
    def add_event_handler(self,*_):pass
    async def __call__(self,_):return True  # Only offline status on backend.close; no auth/RPC emulation.
    async def connect_stream(self,operation,number):
        reader,writer=await asyncio.open_connection('127.0.0.1',self.lab.port,limit=2*CHUNK)
        self.writers.add(writer);writer.write(operation+struct.pack('!I',number));await writer.drain()
        return reader,writer
    async def close_stream(self,writer):
        self.writers.discard(writer);writer.close()
        try:await writer.wait_closed()
        except (ConnectionError,OSError):pass
    async def disconnect(self):
        await asyncio.gather(*(self.close_stream(writer) for writer in list(self.writers)))
    async def download_media(self,media,*,file,progress_callback,thumb):
        reader,writer=await self.connect_stream(b'D',media.id);self.streams.append(file)
        try:
            while chunk:=await reader.read(CHUNK):
                file.write(chunk)
                await progress_callback(file.tell(),media.size)
            return file  # Deliberate successful short EOF: backend must enforce declared document size.
        finally:await self.close_stream(writer)
    async def send_file(self,peer,file,*,progress_callback,**_):
        self.send_calls+=1;self.streams.append(file)
        reader,writer=await self.connect_stream(b'U',peer)
        length=file.seek(0,2);file.seek(0);writer.write(struct.pack('!Q',length));await writer.drain()
        try:
            while chunk:=file.read(CHUNK):
                writer.write(chunk);await writer.drain()
                await reader.readexactly(1)
                await progress_callback(file.tell(),length)
            if await reader.readexactly(2)!=b'OK':raise ConnectionError('Missing local send confirmation')
            return 'acknowledged'
        finally:await self.close_stream(writer)


class ProbeClient:
    _updates_error=None
    def __init__(self,lab):self.lab=lab;self.reader=self.writer=None;self.connects=self.disconnects=0
    def is_connected(self):return self.writer is not None and not self.writer.is_closing()
    async def connect(self):
        self.connects+=1
        self.reader,self.writer=await asyncio.open_connection('127.0.0.1',self.lab.port)
        self.writer.write(b'R');await self.writer.drain()
    async def disconnect(self):
        self.disconnects+=1
        if self.writer:
            self.writer.close();await self.writer.wait_closed();self.reader=self.writer=None
    async def __call__(self,_):
        self.writer.write(b'P');await self.writer.drain()
        return await self.reader.readexactly(1)
    async def catch_up(self):await self(None)


async def scenarios(root):
    results=[]
    for rate in (512*1024,64*1024,16*1024):
        async with Lab() as lab:
            media=lab.document(rate=rate,latency=.2)
            client=SocketClient(lab);backend=TelegramBackend(client);backend.message=lambda value:value
            target=root/f'download-{rate}.bin';progress=[];ticks=[];running=True
            async def heartbeat():
                while running:ticks.append(time.perf_counter());await asyncio.sleep(.01)
            timer=asyncio.create_task(heartbeat());started=time.perf_counter();cpu_started=time.process_time()
            try:
                with patch('tg_ascii.telegram_features.DOWNLOAD_IDLE_TIMEOUT',.8):
                    await backend.download_media(media,target,lambda n,total:progress.append((n,total)))
            finally:running=False;await timer
            elapsed=time.perf_counter()-started
            assert target.read_bytes()==PAYLOAD
            assert progress[-1]==(len(PAYLOAD),len(PAYLOAD))
            assert all(a[0]<b[0] for a,b in zip(progress,progress[1:]))
            assert len(progress)<=len(PAYLOAD)//CHUNK
            assert len(ticks)>10
            started=time.perf_counter();upload_progress=[]
            with patch('tg_ascii.transfers.UPLOAD_IDLE_TIMEOUT',.8):
                assert await backend.send_attachment(1,target,lambda n,total:upload_progress.append((n,total)))=='acknowledged'
            upload_elapsed=time.perf_counter()-started
            assert lab.uploads==[PAYLOAD] and client.send_calls==1
            assert upload_progress[-1]==(len(PAYLOAD),len(PAYLOAD))
            assert all(stream.closed for stream in client.streams)
            await backend.close()
            results.append({'scenario':'paced_upload_download','bytes_per_second':rate,'latency_seconds':.2,
                            'bytes':len(PAYLOAD),'sha256':hashlib.sha256(PAYLOAD).hexdigest(),
                            'download_seconds':elapsed,'upload_seconds':upload_elapsed,
                            'cpu_seconds':time.process_time()-cpu_started,
                            'progress_callbacks':len(progress),'event_loop_ticks':len(ticks),
                            'max_event_loop_gap_seconds':max(b-a for a,b in zip(ticks,ticks[1:]))})
    async with Lab() as lab:
        client=SocketClient(lab);backend=TelegramBackend(client);target=root/'preserved.bin';target.write_bytes(b'original')
        media=lab.document(cut=3*CHUNK)
        try:await backend.download_media(media,target)
        except OSError:pass
        else:raise AssertionError('truncated document was published')
        assert target.read_bytes()==b'original' and lab.downloads==1
        assert not list(root.glob('.tg-download-*'))
        await backend.close();results.append({'scenario':'truncated_eof','bytes_before_cut':3*CHUNK,'old_destination_preserved':True,'attempts':lab.downloads})
    async with Lab() as lab:
        media=lab.document(stall=True);client=SocketClient(lab);backend=TelegramBackend(client)
        started=time.perf_counter()
        with patch('tg_ascii.telegram_features.DOWNLOAD_IDLE_TIMEOUT',.2):
            try:await backend.download_media(media,root/'stalled.bin')
            except TimeoutError:pass
            else:raise AssertionError('stalled socket did not time out')
        assert not (root/'stalled.bin').exists() and not list(root.glob('.tg-download-*'))
        assert all(stream.closed for stream in client.streams) and not client.writers
        await backend.close();results.append({'scenario':'stalled_socket','seconds':time.perf_counter()-started,'cleaned':True})
    async with Lab() as lab:
        media=lab.document(stall=True);client=SocketClient(lab);backend=TelegramBackend(client)
        tasks=[asyncio.create_task(backend.download_media(media,root/f'queued-{i}.bin')) for i in range(40)]
        await lab.wait_connections(4)
        assert lab.connections==4 and len(list(root.glob('.tg-download-*')))==4
        started=time.perf_counter();await backend.close()
        outcomes=await asyncio.gather(*tasks,return_exceptions=True)
        assert all(isinstance(value,asyncio.CancelledError) for value in outcomes)
        assert lab.connections==4 and not backend._transfer_tasks and not client.writers
        assert not list(root.glob('.tg-download-*'))
        results.append({'scenario':'close_with_40_downloads','opened_connections':lab.connections,
                        'peak_connections':lab.peak,'cancelled':len(outcomes),'close_seconds':time.perf_counter()-started})
    async with Lab() as lab:
        lab.document(7,ambiguous=True);client=SocketClient(lab);backend=TelegramBackend(client)
        target=root/'ambiguous.bin';target.write_bytes(PAYLOAD)
        try:await backend.send_attachment(7,target)
        except asyncio.IncompleteReadError:pass
        else:raise AssertionError('ambiguous upload was treated as confirmed')
        assert lab.uploads==[PAYLOAD] and client.send_calls==1 and target.read_bytes()==PAYLOAD
        assert all(stream.closed for stream in client.streams)
        await backend.close();results.append({'scenario':'lost_send_confirmation','server_received_full_file':True,'send_attempts':1,'source_preserved':True})
    async with Lab() as lab:
        client=ProbeClient(lab);await client.connect()
        recovery=Recovery(NS(client=client,root=root,on_change=None))
        try:
            with patch('tg_ascii.recovery.PROBE_TIMEOUT',.15):
                await asyncio.gather(*(recovery.ensure() for _ in range(30)))
            assert client.connects==2 and client.disconnects==1 and recovery.state=='online'
            assert lab.control_connections==2 and lab.control_probes==2
            results.append({'scenario':'dead_socket_recovery_30_waiters','initial_plus_reconnect':client.connects,
                            'disconnects':client.disconnects,'healthy_probe_and_catchup':lab.control_probes})
        finally:await recovery.stop();await client.disconnect()
    assert not list(root.glob('.tg-download-*'))
    return results


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='tg-network-lab-') as directory:
        started=time.perf_counter()
        results=asyncio.run(scenarios(Path(directory)))
    report={'success':True,'transport':'real TCP 127.0.0.1 only; application adapter, not MTProto',
            'seconds':time.perf_counter()-started,'scenarios':results}
    output=json.dumps(report,indent=2)+'\n'
    if args.output:args.output.write_text(output,encoding='utf-8')
    print(output)


if __name__=='__main__':main()
