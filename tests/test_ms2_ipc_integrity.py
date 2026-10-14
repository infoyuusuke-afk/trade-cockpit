"""Synthetic IPC fault model; never imports or starts Watcher/Excel."""
import json
import os
import struct
import subprocess
import tempfile
import time
import unittest
from multiprocessing import get_context, shared_memory
from pathlib import Path
from scripts import ms2_ipc_integrity as ipc
from scripts import ms2_nonblocking_handoff as h
from scripts.ms2_ps_python_bridge import start_bridge, publish_into, stamp_header
from tests.test_ms2_ps_python_bridge import _board, ROOT, RELATIVE


def crash_holding(name):
    shm = shared_memory.SharedMemory(name=name)
    if not ipc.acquire(shm.buf):
        os._exit(90)
    # Deliberately leave a plausible partial record and a reserved envelope.
    struct.pack_into('<Q', shm.buf, ipc.META_BASE, 0)
    shm.buf[4096:4100] = b'NBH1'
    os._exit(91)


class IntegrityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.sessions = []

    def tearDown(self):
        for session in self.sessions:
            session.stop(.1)
        self.tmp.cleanup()

    def start(self, **kw):
        s = start_bridge(self.root, RELATIVE, enabled=True, **kw)
        self.sessions.append(s)
        self.assertEqual(s.status, 'STARTED', s.reason)
        return s

    def wait(self, predicate):
        end = time.monotonic() + 5
        while time.monotonic() < end:
            if predicate(): return
            time.sleep(.005)
        self.fail('deadline')

    def test_envelope_faults_never_persist(self):
        for field in ('marker', 'generation', 'sequence', 'length', 'checksum', 'payload'):
            with self.subTest(field=field):
                s = self.start(fault=h.FAULT_HOLD)
                self.assertEqual(s.submit_capture(_board())['status'], 'ACCEPTED')
                self.assertTrue(ipc.acquire(s._shm.buf))
                try:
                    offsets = dict(marker=512, generation=520, sequence=528,
                                   length=536, checksum=544, payload=4096+472)
                    s._shm.buf[offsets[field]] ^= 1
                finally: ipc.release(s._shm.buf)
                s.set_fault(0)
                self.wait(lambda: s.metrics()['fail_closed'] == 1)
                self.assertEqual(s.metrics()['durable'], 0)
                self.assertFalse((self.root / RELATIVE).exists())
                s.stop()

    def test_native_gate_excludes_other_process(self):
        s = self.start(fault=h.FAULT_HOLD)
        self.assertTrue(ipc.acquire(s._shm.buf))
        try:
            packed = h.pack_capture(_board())['record']
            self.assertEqual(publish_into(s._shm.buf, packed, s._generation)['reason'], 'PRODUCER_BUSY')
            from scripts.ms2_ps_python_bridge import _attached_publish_main
            ctx = get_context('spawn'); parent, child = ctx.Pipe()
            proc = ctx.Process(target=_attached_publish_main, args=(s.map_name, packed, child))
            proc.start(); self.assertTrue(parent.poll(3))
            self.assertEqual(parent.recv(), 'REFUSED'); proc.join(3)
            self.assertEqual(proc.exitcode, 0)
            self.assertEqual(h._load(s._shm.buf, h._OFF_WRITE), 0)
        finally: ipc.release(s._shm.buf)

    def test_actual_producer_exit_mid_slot_fences_map(self):
        s = self.start(fault=h.FAULT_HOLD)
        ctx=get_context('spawn'); p=ctx.Process(target=crash_holding,args=(s.map_name,))
        p.start(); p.join(3); self.assertEqual(p.exitcode,91)
        self.wait(lambda: s.metrics()['fail_closed'] == 1)
        self.assertEqual(s.submit_capture(_board())['status'], 'REFUSED')
        self.assertEqual(s.metrics()['durable'], 0)
        self.assertFalse((self.root / RELATIVE).exists())
        old_name=s.map_name; old_gen=s._generation
        s.stop(); s._process.join(3)
        new=self.start()
        self.assertNotEqual(new.map_name,old_name)
        self.assertNotEqual(new._generation,old_gen)
        self.assertEqual(new.metrics()['queued'],0)

    def test_consumer_killed_inside_read_gate_cannot_reuse_map(self):
        s=self.start(fault=h.FAULT_CONSUMER_GATE)
        self.assertEqual(s.submit_capture(_board())['status'],'ACCEPTED')
        self.wait(lambda:struct.unpack_from('<I',s._shm.buf,ipc.GATE)[0]==1)
        s._process.kill();s._process.join(3)
        self.assertFalse(s._process.is_alive())
        self.assertEqual(s.submit_capture(_board())['reason'],'PRODUCER_BUSY')
        self.assertEqual(s.observe_owner()['status'],'WORKER_DEAD')
        self.assertFalse((self.root/RELATIVE).exists())
        s.stop();new=self.start()
        self.assertEqual(new.metrics()['queued'],0)

    def test_consumer_rejects_index_rollback_and_valid_old_slot(self):
        s=self.start()
        self.assertEqual(s.submit_capture(_board())['status'],'ACCEPTED')
        self.wait(lambda:s.metrics()['durable']==1)
        raw=(self.root/RELATIVE).read_bytes()
        s.set_fault(h.FAULT_HOLD)
        self.assertTrue(ipc.acquire(s._shm.buf))
        try:struct.pack_into('<QQ',s._shm.buf,0,1,0)
        finally:ipc.release(s._shm.buf)
        self.wait(lambda:s.metrics()['fail_closed']==1)
        self.assertEqual((self.root/RELATIVE).read_bytes(),raw)
        self.assertEqual(s.metrics()['durable'],1)

    @unittest.skipUnless(os.name=='nt','actual Windows mapping DACL')
    def test_windows_actual_acl_broad_grant_refused(self):
        from ctypes import wintypes as w
        import ctypes, uuid
        name='b'+uuid.uuid4().hex[:11]
        shm=shared_memory.SharedMemory(create=True,name=name,size=h.SHM_SIZE)
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        adv=ctypes.WinDLL('advapi32',use_last_error=True)
        kernel.OpenFileMappingW.argtypes=[w.DWORD,w.BOOL,w.LPCWSTR];kernel.OpenFileMappingW.restype=w.HANDLE
        kernel.CloseHandle.argtypes=[w.HANDLE];kernel.LocalFree.argtypes=[ctypes.c_void_p]
        adv.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes=[w.LPCWSTR,w.DWORD,ctypes.POINTER(ctypes.c_void_p),ctypes.c_void_p]
        adv.GetSecurityDescriptorDacl.argtypes=[ctypes.c_void_p,ctypes.POINTER(w.BOOL),ctypes.POINTER(ctypes.c_void_p),ctypes.POINTER(w.BOOL)]
        adv.SetSecurityInfo.argtypes=[w.HANDLE,ctypes.c_int,w.DWORD,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p]
        handle=None;sd=ctypes.c_void_p()
        try:
            self.assertEqual(ipc.windows_acl_audit(name)['status'],'PASS')
            handle=kernel.OpenFileMappingW(0x40000,False,name);self.assertTrue(handle)
            self.assertTrue(adv.ConvertStringSecurityDescriptorToSecurityDescriptorW('D:(A;;GA;;;WD)',1,ctypes.byref(sd),None))
            present=w.BOOL();defaulted=w.BOOL();dacl=ctypes.c_void_p()
            self.assertTrue(adv.GetSecurityDescriptorDacl(sd,ctypes.byref(present),ctypes.byref(dacl),ctypes.byref(defaulted)))
            self.assertEqual(adv.SetSecurityInfo(handle,6,4,None,None,dacl,None),0)
            with self.assertRaisesRegex(ValueError,'ACL_UNTRUSTED_GRANT'):
                ipc.windows_acl_audit(name)
        finally:
            if sd.value:kernel.LocalFree(sd)
            if handle:kernel.CloseHandle(handle)
            shm.close()

    def test_aba_slot_and_wraparound_refused(self):
        buf=bytearray(h.SHM_SIZE);stamp_header(buf,17)
        blob=h.pack_capture(_board())['record']
        ipc.seal(buf,blob,17,0)
        self.assertEqual(ipc.read_slot(buf,17,0),blob)
        with self.assertRaises(ValueError):ipc.read_slot(buf,17,8)
        with self.assertRaises(ValueError):ipc.read_slot(buf,18,0)
        struct.pack_into('<QQ',buf,0,ipc.LIMIT,ipc.LIMIT)
        result=publish_into(buf,blob,17)
        self.assertEqual(result['reason'],'IPC_SEQUENCE_CORRUPT')
        self.assertEqual(h._load(buf,h._OFF_WRITE),ipc.LIMIT)

    def test_legacy_header_and_negative_indices_refused(self):
        for offset,value in ((180,1),(0,1<<63),(8,1)):
            buf=bytearray(h.SHM_SIZE);stamp_header(buf,17)
            if offset==180:buf[offset]=value
            else:struct.pack_into('<Q',buf,offset,value)
            r=publish_into(buf,h.pack_capture(_board())['record'],17)
            self.assertEqual(r['status'],'DROPPED')
            self.assertEqual(h._load(buf,h._OFF_QUEUED),0)

    @unittest.skipUnless(os.name=='nt','PS5.1 Windows synthetic')
    def test_windows_actual_ps_faults_and_tail(self):
        s=self.start(fault=h.FAULT_HOLD)
        result=subprocess.run(['powershell.exe','-NoProfile','-File',
            str(ROOT/'tests/ms2_ipc_fault_producer.ps1'),'-MapName',s.map_name,
            '-Mode','timing'],capture_output=True,text=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stderr)
        timing=json.loads(result.stdout.strip());print('WINDOWS_IPC_SUBMIT='+json.dumps(timing,sort_keys=True))
        self.assertEqual(timing['samples'],200)
        self.assertEqual(timing['accepted'],8)
        self.assertEqual(timing['dropped'],192)
        self.assertEqual(s.metrics()['durable'],0)
        s.set_fault(0);self.wait(lambda:s.metrics()['durable']+h._load(s._shm.buf,h._OFF_DUPLICATES)==8)
        raw=(self.root/RELATIVE).read_bytes();row=json.loads(raw)
        self.assertFalse(row['snapshot_atomic']);self.assertEqual(row['sequence_basis'],'POLL')
        self.assertIsNone(row['available_at']);self.assertIsNone(row['levels'][0]['bid_qty'])
        self.assertEqual(row['levels'][0]['ask_qty'],0)
        s.stop();s._process.join(3)
        s=self.start(fault=h.FAULT_HOLD)
        p=subprocess.Popen(['powershell.exe','-NoProfile','-File',str(ROOT/'tests/ms2_ipc_fault_producer.ps1'),
                            '-MapName',s.map_name,'-Mode','crash'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        try:
            self.assertEqual(p.stdout.readline().strip(),'HELD')
            p.kill();p.wait(5)
            self.wait(lambda:s.metrics()['fail_closed']==1)
            self.assertEqual(s.metrics()['durable'],0)
            self.assertEqual((self.root/RELATIVE).read_bytes(),raw)
        finally:
            if p.poll() is None:p.kill();p.wait(5)
