"""TEMP collect exact failing input cases, not source/release acceptance."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
p=argparse.ArgumentParser()
p.add_argument('--source',type=Path,required=True)
p.add_argument('--output',type=Path,required=True)
a=p.parse_args()
root=a.source.resolve()
a.output.mkdir(parents=True,exist_ok=False)
os.environ['PYTHONDONTWRITEBYTECODE']='1'
assert subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip()=='052033e46ed014482b3ecf7c0fee337beb9b91cd'
spec=importlib.util.spec_from_file_location('probe_runner',root/'tests/run_all.py')
r_spec = spec
assert r_spec is not None and r_spec.loader is not None
r=importlib.util.module_from_spec(r_spec);r_spec.loader.exec_module(r)
setattr(r, 'interpreter', lambda:sys.executable)
bare=a.output/'bare_input.py'
bare.write_text('''from PySide6.QtCore import Qt,QPoint,QCoreApplication,QEvent
from PySide6.QtWidgets import QApplication
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtTest import QTest
import time
app=QApplication([])
view=QWebEngineView();view.resize(600,320);view.show()
loaded=[];view.loadFinished.connect(loaded.append)
view.setHtml("<html><head><title>ready</title></head><body style='margin:0;background:#123646'><button style='position:absolute;left:20px;top:96px;width:220px;height:52px' onclick=\\"document.title='clicked'\\">click</button></body></html>")
def wait(fn):
 end=time.monotonic()+10
 while time.monotonic()<end:
  app.processEvents()
  if fn():return True
  QTest.qWait(20)
 return False
try:
 assert wait(lambda:loaded and loaded[-1] and not view.page().isLoading()),'bare load failed'
 view.setFocus();QTest.mouseClick(view.focusProxy(),Qt.LeftButton,pos=QPoint(80,116))
 assert wait(lambda:view.title()=='clicked'),('bare input never arrived',view.title(),view.page().isLoading())
 print('PASS bare_input',flush=True)
finally:
 view.close();view.deleteLater();QCoreApplication.sendPostedEvents(None,QEvent.DeferredDelete);app.processEvents()
''')
compile(bare.read_text(),str(bare),'exec')
cases=['test_blob_raw_text_download_prompts_and_saves_exact_bytes','test_hub_close_cancels_in_progress_download','test_same_tab_raw_link_has_visible_back_forward_reload']
rows=[]
for repeat in range(2):
 for label,path,extra in [('bare',bare,[])]+[(name,root/'tests/test_browser_controls.py',['--test='+name]) for name in cases]:
  code,text=r.run_one(path,True,extra)
  log=a.output/f'{repeat}-{label}.log';log.write_text(text)
  rows.append(dict(repeat=repeat,case=label,raw_exit=code,passed=re.findall(r'(?m)^PASS (\w+)',text),failed=re.findall(r'(?m)^FAIL (\w+)',text),log=log.name))
  (a.output/'observations.json').write_text(json.dumps(dict(scope='diagnostic collection only; no source/release acceptance',python=platform.python_version(),qpa=os.environ.get('QT_QPA_PLATFORM'),rows=rows),indent=2)+'\n')
print(json.dumps(rows,indent=2),flush=True)
assert len(rows)==8
# A green diagnostic job means observations were collected, NOT that cases passed.
