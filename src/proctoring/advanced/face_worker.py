"""Private bounded JSON pipe. Never emits images or embeddings."""
import base64
import contextlib
import json
import sys


def watch_parent(pid):
    """Keep an OS process handle, so PID reuse cannot keep an orphan alive."""
    import os
    import threading
    if os.name!='nt': return
    import ctypes
    from ctypes import wintypes as W
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.OpenProcess.argtypes=[W.DWORD,W.BOOL,W.DWORD];kernel.OpenProcess.restype=W.HANDLE
    kernel.WaitForSingleObject.argtypes=[W.HANDLE,W.DWORD];kernel.WaitForSingleObject.restype=W.DWORD
    kernel.CloseHandle.argtypes=[W.HANDLE];kernel.CloseHandle.restype=W.BOOL
    handle=kernel.OpenProcess(0x00100000,False,pid) # SYNCHRONIZE, no inspection/termination rights
    if not handle: raise RuntimeError('parent_handle_unavailable')
    def wait():
        try: kernel.WaitForSingleObject(handle,0xffffffff)
        finally:
            kernel.CloseHandle(handle)
            os._exit(2)
    threading.Thread(target=wait,daemon=True,name='face-parent-lifetime').start()


def main():
    output=sys.stdout
    def emit(value):
        output.write(json.dumps(value,allow_nan=False)+'\n');output.flush()
    # Library chatter cannot corrupt the protocol. Parent drains stderr too.
    with contextlib.redirect_stdout(sys.stderr):
        from face_runtime import Analyzer
        config=json.loads(sys.stdin.readline(16384))
        watch_parent(config['parent_pid'])
        engine=Analyzer(config['root'],config['config'],config['session'])
        emit({'state':'ready'})
        import cv2
        import numpy as np
        while True:
            line=sys.stdin.readline(2_000_001)
            if not line: break
            if len(line)>2_000_000: raise ValueError('input_limit')
            request=json.loads(line)
            image=cv2.imdecode(np.frombuffer(base64.b64decode(request.pop('jpeg'),validate=True),np.uint8),cv2.IMREAD_COLOR)
            if image is None or image.shape[0]>480 or image.shape[1]>640: raise ValueError('image_limit')
            try: result=engine.analyze(image,request)
            except ValueError: result={'identity':'inconclusive','liveness':'inconclusive'}
            emit({'state':'result','session':request['session'],'sequence':request['sequence'],
                  'timestamp':request['timestamp'],'generation':request['generation'],**result})


if __name__=='__main__':
    try: main()
    except Exception:
        # No payload/embedding/PII in exception diagnostics.
        sys.stderr.write('optional_face_worker_failed\n')
        raise SystemExit(1)
