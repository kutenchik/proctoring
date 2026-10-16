"""Generated arrays only: CPU compatibility/latency, never accuracy or admission."""
from pathlib import Path
import sys
import json
import time
import platform
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src/proctoring/advanced'))
from face_runtime import initialize


def main():
    import numpy as np
    began=time.perf_counter()
    api=initialize(sys.argv[1],True,True)
    warmup=time.perf_counter()-began
    model=api.build_model('Fasnet',task='spoofing')
    image=np.random.default_rng(7).integers(0,256,(240,320,3),dtype=np.uint8)
    samples=[]
    for _ in range(6):
        began=time.perf_counter();cpu=time.process_time()
        model.analyze(image,(100,60,100,120))
        values=api.represent(image[60:180,100:200],model_name='Facenet512',detector_backend='skip',enforce_detection=False,align=False)
        samples.append({'wall_ms':1000*(time.perf_counter()-began),'cpu_ms':1000*(time.process_time()-cpu),
                        'dimensions':len(values[0]['embedding'])})
    import ctypes
    from ctypes import wintypes as W
    class Memory(ctypes.Structure):
        _fields_=[('cb',W.DWORD),('faults',W.DWORD)]+[(name,ctypes.c_size_t) for name in
            ('peak_working','working','peak_paged','paged','peak_nonpaged','nonpaged','pagefile','peak_pagefile')]
    kernel=ctypes.WinDLL('kernel32');psapi=ctypes.WinDLL('psapi')
    kernel.GetCurrentProcess.restype=W.HANDLE
    psapi.GetProcessMemoryInfo.argtypes=[W.HANDLE,ctypes.POINTER(Memory),W.DWORD]
    memory=Memory();memory.cb=ctypes.sizeof(memory)
    ok=psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(),ctypes.byref(memory),memory.cb)
    result={'generated_arrays_only':True,'accuracy_tested':False,'python':platform.python_version(),
        'platform':platform.platform(),'cpu':platform.processor(),'warmup_seconds':warmup,
        'peak_working_set_mib':memory.peak_working/1048576 if ok else None,'samples':samples}
    print(json.dumps(result,indent=2))
    Path(sys.argv[2]).write_text(json.dumps(result,indent=2),encoding='utf-8')


if __name__=='__main__':main()
