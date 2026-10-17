"""Validation-only Windows host guards. Not application resource containment."""
import ctypes
import hashlib
import json
import math
import os
from pathlib import Path
import time
import subprocess
import sys

MIB=1024*1024
LOW_PROFILE=dict(processes=32,memory_mib=1024,cpu_percent=25)


def atomic_json(path,value):
    """Never truncate a committed marker; interrupted replacement keeps prior JSON."""
    path=Path(path);pending=path.with_name(path.name+'.pending')
    try:
        with pending.open('w',encoding='utf-8') as stream:
            json.dump(value,stream,indent=2);stream.flush();os.fsync(stream.fileno())
        os.replace(pending,path)
    finally:
        try:pending.unlink(missing_ok=True)
        except OSError:pass


def read_marker(path):
    """Missing/empty/partial diagnostics are unknown, never a fabricated success."""
    path=Path(path)
    try:
        if path.stat().st_size>65536:return dict(state='oversized',value=None)
        raw=path.read_bytes()
    except FileNotFoundError:return dict(state='missing',value=None)
    except OSError as exc:return dict(state='unreadable',value=None,error_type=type(exc).__name__)
    info=dict(bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest(),value=None)
    if not raw.strip():return dict(info,state='empty')
    try:value=json.loads(raw.decode('utf-8'))
    except (UnicodeError,ValueError):return dict(info,state='invalid_json')
    if not isinstance(value,dict) or not isinstance(value.get('stage'),str):return dict(info,state='invalid_schema')
    return dict(info,state='valid',value=value)


def cpu_usage(previous,current):
    idle,kernel,user=[b-a for a,b in zip(previous,current)]
    total=kernel+user
    if min(idle,kernel,user)<0 or total<=0 or idle>total:
        raise RuntimeError('NOT VERIFIED: invalid Windows CPU accounting sample')
    return 100*(total-idle)/total


class WindowsHostProbe:
    def __init__(self):
        if os.name!='nt':raise RuntimeError('NOT VERIFIED: Windows host telemetry unavailable on this platform')
        self.api=ctypes.WinDLL('kernel32',use_last_error=True);self.previous=None
        self.api.GlobalMemoryStatusEx.argtypes=[ctypes.c_void_p];self.api.GlobalMemoryStatusEx.restype=ctypes.c_int
        self.api.GetSystemTimes.argtypes=[ctypes.POINTER(ctypes.c_uint64)]*3;self.api.GetSystemTimes.restype=ctypes.c_int
    def sample(self):
        class Memory(ctypes.Structure):
            _fields_=[('length',ctypes.c_uint32),('load',ctypes.c_uint32)]+[(n,ctypes.c_uint64) for n in
                ('total','available','commit_limit','available_commit','virtual','available_virtual','extended')]
        mem=Memory();mem.length=ctypes.sizeof(mem)
        if not self.api.GlobalMemoryStatusEx(ctypes.byref(mem)):
            raise RuntimeError('NOT VERIFIED: Windows memory telemetry failed')
        values=[ctypes.c_uint64() for _ in range(3)]
        if not self.api.GetSystemTimes(*(ctypes.byref(v) for v in values)):
            raise RuntimeError('NOT VERIFIED: Windows CPU telemetry failed')
        times=tuple(v.value for v in values)
        cpu=cpu_usage(self.previous,times) if self.previous is not None else None
        self.previous=times
        return dict(time=time.time(),available_memory_mib=int(mem.available//MIB),total_memory_mib=int(mem.total//MIB),
            available_commit_mib=int(mem.available_commit//MIB),cpu_percent=cpu)


def assess_host(sample,preflight=False):
    """Conservative stop thresholds, not hardware suitability certification."""
    memory_floor,commit_floor=(1536,2048) if preflight else (768,1024)
    for name,floor in [('available_memory_mib',memory_floor),('available_commit_mib',commit_floor)]:
        value=sample.get(name)
        if not isinstance(value,(int,float)) or not math.isfinite(value) or value<floor:
            return 'NOT VERIFIED: insufficient '+name+'; close other applications and retry after the machine settles'
    cpu=sample.get('cpu_percent')
    if not isinstance(cpu,(int,float)) or not math.isfinite(cpu) or not 0<=cpu<=100:
        return 'NOT VERIFIED: CPU pressure was not measured'
    if preflight and cpu>60:return 'NOT VERIFIED: host CPU pressure exceeds the 60% preflight threshold'
    return ''


class HostGuard:
    def __init__(self,output,probe=None):
        self.output=Path(output);self.output.parent.mkdir(parents=True,exist_ok=True)
        self.probe=probe or WindowsHostProbe();self.high_cpu=0;self.history=[]
    def observe(self,stage,preflight=False):
        sample=self.probe.sample();sample.update(stage=stage,preflight=preflight)
        if not preflight:
            self.high_cpu=self.high_cpu+1 if (sample.get('cpu_percent') or 0)>85 else 0
        reason=assess_host(sample,preflight)
        if not reason and self.high_cpu>=3:reason='NOT VERIFIED: sustained host CPU pressure above 85%'
        sample['stop_reason']=reason
        # Append-only audit trail avoids repeatedly allocating an ever-growing JSON array.
        with self.output.open('a',encoding='utf-8') as stream:stream.write(json.dumps(sample)+'\n')
        self.history.append(sample)
        if len(self.history)>8:self.history.pop(0)
        if reason:raise RuntimeError(reason)
        return sample
    def preflight(self,stage):
        self.probe.sample();time.sleep(1)
        return self.observe(stage,preflight=True)

class ValidationStageJob:
    """Validation-only lifecycle/commit/process Job; no CPU cap to distort native probes.

    The stage wrapper reads stdin before starting the target command. All normal
    descendants enter this Job; production worker Jobs remain nested and unchanged.
    """
    def __init__(self,process):
        from ctypes import wintypes as w
        c=ctypes
        class Basic(c.Structure):
            _fields_=[('ProcessTime',c.c_int64),('JobTime',c.c_int64),('Flags',w.DWORD),
                ('MinWS',c.c_size_t),('MaxWS',c.c_size_t),('ActiveLimit',w.DWORD),
                ('Affinity',c.c_size_t),('Priority',w.DWORD),('Scheduling',w.DWORD)]
        class Extended(c.Structure):
            _fields_=[('Basic',Basic),('IO',c.c_uint64*6),('ProcessMemory',c.c_size_t),
                ('JobMemory',c.c_size_t),('PeakProcess',c.c_size_t),('PeakJob',c.c_size_t)]
        class Accounting(c.Structure):
            _fields_=[('Times',c.c_int64*4),('Faults',w.DWORD),('Total',w.DWORD),('Active',w.DWORD),('Terminated',w.DWORD)]
        self.Accounting=Accounting;self.api=c.WinDLL('kernel32',use_last_error=True)
        for name,args,result in [
            ('CreateJobObjectW',[c.c_void_p,w.LPCWSTR],w.HANDLE),
            ('SetInformationJobObject',[w.HANDLE,c.c_int,c.c_void_p,w.DWORD],w.BOOL),
            ('AssignProcessToJobObject',[w.HANDLE,w.HANDLE],w.BOOL),
            ('QueryInformationJobObject',[w.HANDLE,c.c_int,c.c_void_p,w.DWORD,c.c_void_p],w.BOOL),
            ('TerminateJobObject',[w.HANDLE,w.UINT],w.BOOL),('CloseHandle',[w.HANDLE],w.BOOL)]:
            fn=getattr(self.api,name);fn.argtypes=args;fn.restype=result
        self.handle=self.api.CreateJobObjectW(None,None)
        if not self.handle:raise RuntimeError('NOT VERIFIED: validation-stage Job unavailable')
        try:
            limits=Extended();limits.Basic.Flags=0x2208
            limits.Basic.ActiveLimit=64;limits.JobMemory=1536*MIB
            if not self.api.SetInformationJobObject(self.handle,9,c.byref(limits),c.sizeof(limits)):
                raise RuntimeError('NOT VERIFIED: validation-stage lifecycle limit unavailable')
            readback=Extended()
            if not self.api.QueryInformationJobObject(self.handle,9,c.byref(readback),c.sizeof(readback),None) or readback.Basic.Flags & 0x2208 != 0x2208 or readback.Basic.ActiveLimit!=64 or readback.JobMemory!=1536*MIB or readback.Basic.Flags & 0x1800:
                raise RuntimeError('NOT VERIFIED: validation-stage cap readback failed')
            self.limits=dict(verified=True,processes=64,committed_memory_mib=1536,cpu_rate_cap='not configured')
            if not self.api.AssignProcessToJobObject(self.handle,w.HANDLE(int(process._handle))):
                raise RuntimeError('NOT VERIFIED: validation-stage Job assignment failed; input gate remains closed')
        except BaseException:
            self.api.CloseHandle(self.handle);self.handle=None;raise
    def snapshot(self):
        info=self.Accounting()
        if not self.api.QueryInformationJobObject(self.handle,1,ctypes.byref(info),ctypes.sizeof(info),None):
            return dict(available=False)
        return dict(available=True,active_processes=int(info.Active),total_processes=int(info.Total))
    def cleanup(self):
        details=dict(confirmed=False,before=None,after=None,limits=self.limits)
        try:
            details['before']=self.snapshot()
            terminated=bool(self.api.TerminateJobObject(self.handle,1));end=time.monotonic()+5
            while True:
                details['after']=self.snapshot()
                empty=details['after'].get('available') is True and details['after'].get('active_processes')==0
                if empty or time.monotonic()>=end:
                    details['confirmed']=bool(terminated and empty);break
                time.sleep(0.05)
        except Exception as exc:details['error_type']=type(exc).__name__
        finally:
            if self.handle:self.api.CloseHandle(self.handle);self.handle=None
        return details

_stage_running=False

def run_guarded_stage(command,log,cwd,env,timeout,guard):
    """One gated stage at a time; validation-only Job owns every descendant."""
    global _stage_running
    if guard is None or _stage_running:
        raise RuntimeError('NOT VERIFIED: guarded serial execution is unavailable')
    guard.preflight(log.name)
    _stage_running=True
    process=None;job=None;details=dict(stage=log.name,confirmed=False);rc=None
    failure=None;started=time.monotonic()
    try:
        with log.open('w',encoding='utf-8') as stream:
            flags=getattr(subprocess,'CREATE_NEW_PROCESS_GROUP',0x200) | 0x4000  # BELOW_NORMAL_PRIORITY_CLASS
            process=subprocess.Popen([sys.executable,'-u',str(cwd/'tests/validation_stage.py')],
                cwd=cwd,env=env,stdin=subprocess.PIPE,stdout=stream,stderr=subprocess.STDOUT,
                text=True,encoding='utf-8',creationflags=flags)
            job=ValidationStageJob(process)
            process.stdin.write(json.dumps(command));process.stdin.close()
            while True:
                rc=process.poll()
                if rc is not None:break
                if time.monotonic()-started>=timeout:
                    raise RuntimeError('NOT VERIFIED: bounded stage deadline reached: '+log.name)
                try:process.wait(timeout=1)
                except subprocess.TimeoutExpired:pass
                guard.observe(log.name)
    except (Exception,KeyboardInterrupt) as exc:
        failure=exc;details['stop_reason']=type(exc).__name__+': '+str(exc)
    finally:
        if job is not None:details.update(job.cleanup())
        if process is not None:
            if job is None:
                # No command was released through stdin, so no child command exists.
                try:process.kill()
                except OSError:pass
            try:process.wait(timeout=5)
            except (OSError,subprocess.TimeoutExpired):details['confirmed']=False
        details['elapsed_seconds']=round(time.monotonic()-started,6)
        _stage_running=False
        atomic_json(log.with_name(log.stem+'-stage-cleanup.json'),details)
    if not details.get('confirmed'):
        raise RuntimeError('NOT VERIFIED: owned validation-stage cleanup not confirmed; see '+log.stem+'-stage-cleanup.json')
    if failure is not None:raise failure
    time.sleep(2)  # Short idle cooldown, not a worker deadline extension.
    return rc
