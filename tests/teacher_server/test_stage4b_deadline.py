"""Exercise the independent guard without launching or terminating any process."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import pytest

def load(tmp_path,monkeypatch):
    source=Path(__file__).resolve().parents[2]/'scripts/stage4b-exposure-deadline.py'
    spec=importlib.util.spec_from_file_location('deadline_test',source);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    monkeypatch.setattr(module,'__file__',str(tmp_path/'scripts/guard.py'))
    run=tmp_path/'build/stage4b/run';run.mkdir(parents=True)
    monkeypatch.setattr(module.time,'time',lambda:100.)
    return module,run

def test_guard_requires_explicit_approval_before_writing(tmp_path,monkeypatch):
    module,run=load(tmp_path,monkeypatch)
    monkeypatch.setattr(__import__('sys'),'argv',['guard','--run',str(run),'--deadline','160'])
    with pytest.raises(SystemExit):module.main()
    assert not list(run.iterdir())

def test_guard_stops_owned_run_inside_deadline_and_never_reuses_record(tmp_path,monkeypatch):
    module,run=load(tmp_path,monkeypatch);calls=[]
    monkeypatch.setattr(__import__('sys'),'argv',['guard','--operator-approved','--run',str(run),'--deadline','160'])
    monkeypatch.setattr(module.subprocess,'run',lambda argv,**kwargs:(calls.append((argv,kwargs)) or SimpleNamespace(returncode=0)))
    module.main()
    assert len(calls)==1 and calls[0][0][-3:]==['Stop','-RunDirectory',str(run)]
    assert calls[0][1]['timeout']==60
    assert json.loads((run/'deadline-result.json').read_text())['returncode']==0
    with pytest.raises(FileExistsError):module.main()
    assert len(calls)==1

def test_guard_early_verified_close_does_not_terminate_anything(tmp_path,monkeypatch):
    module,run=load(tmp_path,monkeypatch)
    monkeypatch.setattr(__import__('sys'),'argv',['guard','--operator-approved','--run',str(run),'--deadline','900'])
    (run/'closed.json').write_text('{}')
    monkeypatch.setattr(module.subprocess,'run',lambda *a,**k:pytest.fail('must not terminate'))
    module.main()
