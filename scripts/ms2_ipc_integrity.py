"""Offline IPC v2 envelope. Payload/canonical hashes are unchanged.

One non-waiting native CAS fences every cooperating publisher and consumer.
A crashed holder is never unlocked by another participant: abandon the map.
This is integrity, not authentication against a hostile writable attachment.
"""
import ctypes
import ctypes.util
import hashlib
import os
import struct

GATE = 192
META_BASE = 512
META_SIZE = 64
LIMIT = (1 << 63) - 1
HEADER = b'NBH1' + bytes((2, 8)) + struct.pack('<HI', 2048, 20480)

if os.name == 'nt':
    from ctypes import wintypes as w
    import atexit
    _native = ctypes.WinDLL('kernel32', use_last_error=True)
    _native.CreateMutexW.argtypes = [ctypes.c_void_p, w.BOOL, w.LPCWSTR]
    _native.CreateMutexW.restype = w.HANDLE
    _native.WaitForSingleObject.argtypes = [w.HANDLE, w.DWORD]
    _native.WaitForSingleObject.restype = w.DWORD
    _native.ReleaseMutex.argtypes = [w.HANDLE]
    _native.CloseHandle.argtypes = [w.HANDLE]
    _mutexes = {}
    def prepare(generation):
        if generation not in _mutexes:
            handle = _native.CreateMutexW(None, False, 'Local\\ms2ipc-v2-' + str(generation))
            if not handle: raise ValueError('IPC_MUTEX_CREATE_FAILED')
            _mutexes[generation] = handle
    def gate(buf, expected, desired):
        generation = struct.unpack_from('<Q', buf, 112)[0]
        prepare(generation)
        handle = _mutexes[generation]
        if expected == 0:
            status = _native.WaitForSingleObject(handle, 0)
            if status == 0x80: # acquired, but previous holder died
                struct.pack_into('<I', buf, GATE, 1)
                _native.ReleaseMutex(handle)
                return False
            if status != 0: return False
            if struct.unpack_from('<I', buf, GATE)[0] != 0:
                _native.ReleaseMutex(handle)
                return False
            struct.pack_into('<I', buf, GATE, 1)
            return True
        if struct.unpack_from('<I', buf, GATE)[0] != 1:
            _native.ReleaseMutex(handle)
            return False
        struct.pack_into('<I', buf, GATE, 0)
        return bool(_native.ReleaseMutex(handle))
    @atexit.register
    def _close_mutexes():
        for handle in _mutexes.values(): _native.CloseHandle(handle)
else:
    _native = ctypes.CDLL(ctypes.util.find_library('atomic') or 'libatomic.so.1')
    _cas = _native.__atomic_compare_exchange_4
    _cas.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32), ctypes.c_uint32,
                     ctypes.c_bool, ctypes.c_int, ctypes.c_int]
    _cas.restype = ctypes.c_bool
    def prepare(generation): pass
    def gate(buf, expected, desired):
        word = ctypes.c_uint32.from_buffer(buf, GATE)
        old = ctypes.c_uint32(expected)
        return bool(_cas(ctypes.addressof(word), ctypes.byref(old), desired, False, 5, 5))


def acquire(buf):
    return gate(buf, 0, 1)


def release(buf):
    if not gate(buf, 1, 0):
        raise ValueError('IPC_GATE_CORRUPT')


def validate_header(buf, generation):
    if len(buf) != 20480 or bytes(buf[176:188]) != HEADER:
        raise ValueError('IPC_HEADER_CORRUPT')
    gen = struct.unpack_from('<Q', buf, 112)[0]
    write, read = struct.unpack_from('<QQ', buf, 0)
    if gen != generation or not 0 < gen <= LIMIT:
        raise ValueError('GENERATION_MISMATCH')
    if read > write or write - read > 8 or write >= LIMIT:
        raise ValueError('IPC_SEQUENCE_CORRUPT')
    return write, read


def seal(buf, blob, generation, sequence):
    offset = META_BASE + sequence % 8 * META_SIZE
    # Commit is zero until all envelope fields and bytes are copied.
    struct.pack_into('<Q', buf, offset, 0)
    prefix = struct.pack('<QQQ', generation, sequence, len(blob))
    buf[offset + 8:offset + 32] = prefix
    buf[offset + 32:offset + 64] = hashlib.sha256(prefix + blob).digest()
    slot = 4096 + sequence % 8 * 2048
    buf[slot:slot + 2048] = blob
    struct.pack_into('<Q', buf, offset, sequence + 1)


def read_slot(buf, generation, sequence):
    offset = META_BASE + sequence % 8 * META_SIZE
    marker, gen, seq, size = struct.unpack_from('<QQQQ', buf, offset)
    if (marker, gen, seq, size) != (sequence + 1, generation, sequence, 2048):
        raise ValueError('IPC_SLOT_ENVELOPE')
    slot = 4096 + sequence % 8 * 2048
    blob = bytes(buf[slot:slot + 2048])
    prefix = struct.pack('<QQQ', gen, seq, size)
    if bytes(buf[offset + 32:offset + 64]) != hashlib.sha256(prefix + blob).digest():
        raise ValueError('IPC_SLOT_CHECKSUM')
    return blob


def windows_acl_audit(name, *, harden_owned=False):
    """Read actual mapping owner/DACL; never broaden its permissions.

    Allow only current token user, SYSTEM and local Administrators. This
    excludes World/Authenticated Users and inherited unrelated groups.
    Same-user adversarial attachment is explicitly not authenticated.
    """
    if os.name != 'nt':
        return {'status': 'NOT_APPLICABLE'}
    from ctypes import wintypes as w
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    adv=ctypes.WinDLL('advapi32',use_last_error=True)
    kernel.OpenFileMappingW.argtypes=[w.DWORD,w.BOOL,w.LPCWSTR]
    kernel.OpenFileMappingW.restype=w.HANDLE
    kernel.GetCurrentProcess.restype=w.HANDLE
    kernel.CloseHandle.argtypes=[w.HANDLE]
    kernel.LocalFree.argtypes=[ctypes.c_void_p]
    adv.OpenProcessToken.argtypes=[w.HANDLE,w.DWORD,ctypes.POINTER(w.HANDLE)]
    adv.GetTokenInformation.argtypes=[w.HANDLE,ctypes.c_int,ctypes.c_void_p,w.DWORD,ctypes.POINTER(w.DWORD)]
    adv.ConvertSidToStringSidW.argtypes=[ctypes.c_void_p,ctypes.POINTER(w.LPWSTR)]
    adv.GetSecurityInfo.argtypes=[w.HANDLE,ctypes.c_int,w.DWORD,
        ctypes.POINTER(ctypes.c_void_p),ctypes.c_void_p,ctypes.POINTER(ctypes.c_void_p),
        ctypes.c_void_p,ctypes.POINTER(ctypes.c_void_p)]
    adv.GetSecurityInfo.restype=w.DWORD
    adv.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes=[w.LPCWSTR,w.DWORD,ctypes.POINTER(ctypes.c_void_p),ctypes.c_void_p]
    adv.GetSecurityDescriptorDacl.argtypes=[ctypes.c_void_p,ctypes.POINTER(w.BOOL),ctypes.POINTER(ctypes.c_void_p),ctypes.POINTER(w.BOOL)]
    adv.SetSecurityInfo.argtypes=[w.HANDLE,ctypes.c_int,w.DWORD,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p]
    adv.SetSecurityInfo.restype=w.DWORD
    adv.GetAce.argtypes=[ctypes.c_void_p,w.DWORD,ctypes.POINTER(ctypes.c_void_p)]
    def sid_string(ptr):
        output=w.LPWSTR()
        if not adv.ConvertSidToStringSidW(ptr,ctypes.byref(output)):
            raise ValueError('ACL_SID_UNREADABLE')
        try:return output.value
        finally:kernel.LocalFree(ctypes.cast(output,ctypes.c_void_p))
    token=w.HANDLE();handle=None;descriptor=ctypes.c_void_p()
    try:
        if not adv.OpenProcessToken(kernel.GetCurrentProcess(),8,ctypes.byref(token)):
            raise ValueError('ACL_TOKEN_UNREADABLE')
        needed=w.DWORD()
        adv.GetTokenInformation(token,1,None,0,ctypes.byref(needed))
        data=ctypes.create_string_buffer(needed.value)
        if not adv.GetTokenInformation(token,1,data,len(data),ctypes.byref(needed)):
            raise ValueError('ACL_TOKEN_UNREADABLE')
        current=sid_string(ctypes.c_void_p.from_buffer(data).value)
        trusted={current,'S-1-5-18','S-1-5-32-544'}
        handle=kernel.OpenFileMappingW(0x20000 | (0x40000 if harden_owned else 0),False,name)
        if not handle:raise ValueError('ACL_MAP_UNREADABLE')
        owner=ctypes.c_void_p();dacl=ctypes.c_void_p()
        if adv.GetSecurityInfo(handle,6,5,ctypes.byref(owner),None,
                               ctypes.byref(dacl),None,ctypes.byref(descriptor)):
            raise ValueError('ACL_MAP_UNREADABLE')
        if sid_string(owner) not in trusted:
            raise ValueError('ACL_UNSAFE_OWNER')
        if harden_owned:
            # Only called immediately after create=True succeeded. Never
            # modify the DACL of an attached/colliding/unknown map.
            narrowed=ctypes.c_void_p()
            try:
                sddl='D:P(A;;GA;;;'+current+')(A;;GA;;;SY)(A;;GA;;;BA)'
                if not adv.ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl,1,ctypes.byref(narrowed),None):
                    raise ValueError('ACL_NARROW_FAILED')
                present=w.BOOL();defaulted=w.BOOL();new_dacl=ctypes.c_void_p()
                if not adv.GetSecurityDescriptorDacl(narrowed,ctypes.byref(present),ctypes.byref(new_dacl),ctypes.byref(defaulted)):
                    raise ValueError('ACL_NARROW_FAILED')
                if adv.SetSecurityInfo(handle,6,4|0x80000000,None,None,new_dacl,None):
                    raise ValueError('ACL_NARROW_FAILED')
            finally:
                if narrowed.value:kernel.LocalFree(narrowed)
            # Re-read the actual resulting ACL instead of assuming success.
            kernel.LocalFree(descriptor);descriptor=ctypes.c_void_p()
            if adv.GetSecurityInfo(handle,6,5,ctypes.byref(owner),None,
                                   ctypes.byref(dacl),None,ctypes.byref(descriptor)):
                raise ValueError('ACL_MAP_UNREADABLE')
        if not dacl.value:
            raise ValueError('ACL_NULL_DACL')
        # ACL header: revision,size,acecount; ACE allow layout: header,mask,SID.
        header=ctypes.string_at(dacl,8)
        count=struct.unpack_from('<H',header,4)[0]
        allowed=0
        for index in range(count):
            ace=ctypes.c_void_p()
            if not adv.GetAce(dacl,index,ctypes.byref(ace)):
                raise ValueError('ACL_ACE_UNREADABLE')
            kind=ctypes.c_ubyte.from_address(ace.value).value
            if kind == 1: # explicit deny can only restrict
                continue
            if kind != 0:
                raise ValueError('ACL_UNSUPPORTED_ACE')
            if sid_string(ace.value+8) not in trusted:
                raise ValueError('ACL_UNTRUSTED_GRANT')
            allowed+=1
        if not allowed:raise ValueError('ACL_EMPTY_GRANT')
        return {'status':'PASS','untrusted_grants':0,'same_user_authentication':'NOT_VERIFIED'}
    finally:
        if descriptor.value:kernel.LocalFree(descriptor)
        if handle:kernel.CloseHandle(handle)
        if token:kernel.CloseHandle(token)
