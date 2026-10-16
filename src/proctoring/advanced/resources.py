"""Pinned optional resources; runtime verification never downloads."""
from pathlib import Path
import hashlib

VERSION = '0.0.102'
REVISION = 'd1783fe36379546024d548c77e23600a02ce1696'
WEIGHTS = {
    'facenet512_weights.onnx': 'a7a4fbcc6af3175f5c4e91de0b92b4fa387e0e9f141efd59616337220363da33',
    '2.7_80x80_MiniFASNetV2.onnx': '2e0b0bdcdaf2ed0e8ceae7a8588a8b029c0f1bf2b15876eee942b68ce51bbb29',
    '4_0_0_80x80_MiniFASNetV1SE.onnx': '1e2645be6e42759714f19ee23641366cf3d86cba5f169964880894a1fc188275',
    'haarcascade_frontalface_default.xml': '0f7d4527844eb514d4a4948e822da90fbb16a34a0bbbbc6adc6498747a5aafb0',
    'haarcascade_eye.xml': '71cc64fc305a355dc60067880f6fbbd43dd155bd63ee3844661a1bda34b2fd8c',
}


def verify(root, name):
    if name not in WEIGHTS: raise ValueError('unapproved_model')
    path = Path(root)/'.deepface'/'weights'/name
    if path.is_symlink() or not path.is_file(): raise ValueError('model_missing')
    with path.open('rb') as stream: digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    if digest != WEIGHTS[name]: raise ValueError('model_hash_mismatch')
    return path


def prepare(root):
    # Deliberate operator command only; never imported/called by exam startup.
    import urllib.request
    directory = Path(root)/'.deepface'/'weights'
    directory.mkdir(parents=True, exist_ok=True)
    for name in WEIGHTS:
        target = directory/name
        if target.exists(): verify(root,name); continue
        temporary = target.with_suffix('.partial')
        url = (f'https://raw.githubusercontent.com/opencv/opencv/4.9.0/data/haarcascades/{name}' if name.endswith('.xml')
               else f'https://huggingface.co/serengil/deepface/resolve/{REVISION}/{name}')
        with urllib.request.urlopen(url, timeout=30) as source, temporary.open('wb') as output:
            size = 0
            while chunk := source.read(1024*1024):
                size += len(chunk)
                if size > 150_000_000: raise ValueError('resource_size_limit')
                output.write(chunk)
        with temporary.open('rb') as stream: digest=hashlib.file_digest(stream,'sha256').hexdigest()
        if digest != WEIGHTS[name]: raise ValueError('download_hash_mismatch')
        temporary.replace(target)
        print(f'Verified {name}', flush=True)


if __name__ == '__main__':
    import sys
    if len(sys.argv)!=3 or sys.argv[1]!='--prepare': raise SystemExit('Usage: resources.py --prepare DIRECTORY')
    prepare(sys.argv[2])
