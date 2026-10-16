"""Offline pinned DeepFace adapter, imported only in the optional process."""
import importlib.metadata
import os
from pathlib import Path
from resources import VERSION, REVISION, verify


def initialize(root, identity, liveness):
    expected={'deepface':VERSION,'onnxruntime':'1.31.0','numpy':'2.4.6',
              'opencv-contrib-python-headless':'5.0.0.93'}
    for package,version in expected.items():
        if importlib.metadata.version(package)!=version: raise ValueError('face_runtime_version_mismatch')
    os.environ['DEEPFACE_BACKEND_ENGINE']='onnx'
    os.environ['DEEPFACE_HOME']=str(Path(root).resolve())
    os.environ['OMP_NUM_THREADS']='2'
    import cv2
    cv2.setNumThreads(1)
    import onnxruntime as ort
    from deepface.commons import onnx_utils, weight_utils
    def session(file_name, source_url):
        path=verify(root,file_name)
        options=ort.SessionOptions()
        options.intra_op_num_threads=2; options.inter_op_num_threads=1
        options.execution_mode=ort.ExecutionMode.ORT_SEQUENTIAL
        options.log_severity_level=3
        return ort.InferenceSession(str(path),sess_options=options,providers=['CPUExecutionProvider'])
    onnx_utils.build_session=session
    def deny(*args,**kwargs): raise RuntimeError('runtime_download_prohibited')
    weight_utils.download_weights_if_necessary=deny
    # Defense in depth: this dedicated worker has no network purpose.
    import socket
    socket.socket.connect=deny; socket.create_connection=deny
    from deepface import DeepFace
    # OpenCV 5 no longer bundles its XML cascades. Verify and point the official
    # detector at the prepared files; never trust an incidental cv2/data copy.
    from deepface.models.face_detection.OpenCv import OpenCvClient
    cascade=verify(root,'haarcascade_frontalface_default.xml')
    verify(root,'haarcascade_eye.xml')
    OpenCvClient._OpenCvClient__get_opencv_path=lambda self:str(cascade.parent)
    DeepFace.build_model('opencv',task='face_detector')
    if identity: DeepFace.build_model('Facenet512')
    if liveness: DeepFace.build_model('Fasnet',task='spoofing')
    return DeepFace


class Analyzer:
    def __init__(self,root,config,session):
        self.config,self.session=config,session
        self.api=initialize(root,config['identity_enabled'],config['liveness_enabled'])
        self.reference=None

    def analyze(self,image,request):
        import numpy as np
        if request['session']!=self.session: raise ValueError('session_mismatch')
        result={'model':'Facenet512',
                'revision':VERSION,'resource_revision':REVISION,'metric':'cosine'}
        import cv2
        x,y,w,h=request['box']
        crop=image[max(0,y):y+h,max(0,x):x+w]
        if crop.size==0: return {**result,'identity':'low_quality','liveness':'inconclusive'}
        gray=cv2.cvtColor(crop,cv2.COLOR_BGR2GRAY)
        if min(gray.shape)<80 or not 35<=float(gray.mean())<=220 or cv2.Laplacian(gray,cv2.CV_64F).var()<30:
            return {**result,'identity':'low_quality','liveness':'inconclusive'}
        faces=self.api.extract_faces(image,detector_backend='opencv',enforce_detection=True,
            align=True,normalize_face=False,color_face='bgr',
            anti_spoofing=request.get('liveness_due',False))
        if len(faces)!=1: return {**result,'identity':'multiple_faces','liveness':'inconclusive'}
        face=faces[0]; box=face['facial_area']
        x,y,w,h=request['box']; a,b,c,d=box['x'],box['y'],box['w'],box['h']
        overlap=max(0,min(x+w,a+c)-max(x,a))*max(0,min(y+h,b+d)-max(y,b))
        if overlap/max(1,w*h+c*d-overlap)<.4:
            return {**result,'identity':'ambiguous_face','liveness':'inconclusive'}
        if request.get('liveness_due'):
            score=float(face.get('antispoof_score',float('nan')))
            real=face.get('is_real')
            if not np.isfinite(score) or not .8<=score<=1 or type(real) is not bool:
                result['liveness']='inconclusive'
            else: result['liveness']='passed' if real else 'suspected'
            result['antispoof_score']=score if np.isfinite(score) else None
            if result['liveness']!='passed': return {**result,'identity':'liveness_inconclusive'}
        if request.get('identity_due'):
            vectors=self.api.represent(face['face'],model_name='Facenet512',detector_backend='skip',
                enforce_detection=False,align=False,normalization='base')
            vector=np.asarray(vectors[0]['embedding'],dtype=np.float64)
            norm=np.linalg.norm(vector)
            if vector.shape!=(512,) or not np.isfinite(vector).all() or norm<1e-9:
                return {**result,'identity':'low_quality'}
            vector/=norm
            if request.get('enroll'):
                if self.reference is not None: raise ValueError('reference_already_enrolled')
                self.reference=vector
                result['identity']='enrolled'
            elif self.reference is None: result['identity']='reference_required'
            else:
                distance=float(np.clip(1-np.dot(vector,self.reference),0,2))
                result.update(distance=distance,threshold=self.config['facenet_cosine_threshold'],
                    identity='match' if distance<=self.config['facenet_cosine_threshold'] else 'suspected')
        return result
