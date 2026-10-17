"""Compile the zero-capability amd64 proposal with libseccomp; never load it."""
import ctypes as c
import ctypes.util
import json
import struct
import tempfile
from .policy import build,validate

ALLOW=0x7fff0000
ERRNO=0x00050000
AUDIT_AMD64=0xc000003e


class Arg(c.Structure):
    _fields_=[('arg',c.c_uint),('op',c.c_uint),('a',c.c_uint64),('b',c.c_uint64)]


def compile_bpf():
    validate()
    lib=c.CDLL(ctypes.util.find_library('seccomp') or 'libseccomp.so.2')
    lib.seccomp_init.argtypes=[c.c_uint32];lib.seccomp_init.restype=c.c_void_p
    lib.seccomp_release.argtypes=[c.c_void_p]
    lib.seccomp_syscall_resolve_name.argtypes=[c.c_char_p];lib.seccomp_syscall_resolve_name.restype=c.c_int
    lib.seccomp_rule_add_array.argtypes=[c.c_void_p,c.c_uint32,c.c_int,c.c_uint,c.POINTER(Arg)]
    lib.seccomp_export_bpf.argtypes=[c.c_void_p,c.c_int]
    lib.seccomp_arch_native.restype=c.c_uint32
    if lib.seccomp_arch_native()!=AUDIT_AMD64:raise RuntimeError('Reviewed amd64 ABI required')
    context=lib.seccomp_init(ERRNO|1)
    if not context:raise RuntimeError('libseccomp initialization failed')
    try:
        for rule in build()['syscalls']:
            includes=rule.get('includes',{});excludes=rule.get('excludes',{})
            if includes.get('caps'):continue  # Required container capability set is empty.
            if includes.get('arches') and 'amd64' not in includes['arches']:continue
            if 'amd64' in excludes.get('arches',[]):continue
            # The only version gate in the pinned profile is >=4.8. Compile this
            # target explicitly; the host kernel is NOT thereby certified.
            if includes.get('minKernel') not in (None,'4.8'):raise ValueError('Unreviewed kernel condition')
            if set(includes)-{'caps','arches','minKernel'} or set(excludes)-{'caps','arches'}:raise ValueError('Unknown profile condition')
            action=ALLOW if rule['action']=='SCMP_ACT_ALLOW' else ERRNO|rule['errnoRet']
            args=[]
            for arg in rule.get('args',[]):
                op={'SCMP_CMP_NE':1,'SCMP_CMP_EQ':4,'SCMP_CMP_MASKED_EQ':7}[arg['op']]
                args.append(Arg(arg['index'],op,arg['value'],arg.get('valueTwo',0)))
            array=(Arg*len(args))(*args)
            for name in rule['names']:
                syscall=lib.seccomp_syscall_resolve_name(name.encode())
                if syscall==-1:raise RuntimeError('Unsupported syscall name: '+name)
                result=lib.seccomp_rule_add_array(context,action,syscall,len(args),array)
                if result:raise RuntimeError('libseccomp rule rejected: '+name+' '+str(result))
        with tempfile.TemporaryFile() as output:
            if lib.seccomp_export_bpf(context,output.fileno()):raise RuntimeError('BPF export failed')
            output.seek(0);raw=output.read()
        return raw,lib
    finally:lib.seccomp_release(context)


def verdict(raw,nr,args=(),arch=AUDIT_AMD64):
    """Evaluate compiler-emitted classic BPF against synthetic seccomp_data."""
    data=struct.pack('<iI7Q',nr,arch,0,*(list(args)+[0]*6)[:6])
    instructions=[struct.unpack('<HBBI',raw[i:i+8]) for i in range(0,len(raw),8)]
    pc=0;acc=0
    for _ in range(10000):
        code,jt,jf,k=instructions[pc];pc+=1
        if code==0x20:acc=struct.unpack_from('<I',data,k)[0]
        elif code==0x54:acc &= k
        elif code==0x05:pc+=k
        elif code in (0x15,0x25,0x35,0x45):
            condition={0x15:acc==k,0x25:acc>k,0x35:acc>=k,0x45:bool(acc&k)}[code]
            pc+=jt if condition else jf
        elif code==0x06:return k
        else:raise ValueError('Unsupported compiler instruction '+hex(code))
    raise ValueError('BPF evaluation did not terminate')
