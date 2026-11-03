"""Isolated real Chromium MV3 native grant/deny/revoke UI verification.

Requires explicit --public-adafruit and an isolated Xvfb desktop:
  xvfb-run -a -s '-screen 0 1080x1000x24' \
    python3 benchmarks/browser_permission_ui_e2e.py --public-adafruit

A disposable browser profile and the unmodified extension are used.
X11 pointer clicks target Chromium's native permission prompt in this fixed
test viewport. No real user Chrome profile or account is accessed.
"""
import argparse
import json,os,signal,shutil,subprocess,tempfile,time,sys
from pathlib import Path
from urllib.parse import urlsplit
root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root))
from benchmarks.browser_companion_mv3_e2e import (
    cdp, evaluate, get_json, local_broker, enqueue_http, wait_job)
from universal_source_acquisition import acquire_public_product

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument("--public-adafruit",action="store_true")
args=parser.parse_args()
if not args.public_adafruit:
    parser.error("Explicit --public-adafruit required")
target="https://www.adafruit.com/product/1083"
preflight=acquire_public_product(target)
if preflight["status"]!="PRODUCT_CLAIMS_EXTRACTED_NOT_CHECKOUT_VERIFIED" or (
        not preflight.get("robots_checked")):
    raise RuntimeError("Public merchant preflight failed")
if not os.getenv("DISPLAY"):
    raise RuntimeError("Only run under a disposable Xvfb session")
base=Path.home()/'snap/chromium/common'
with tempfile.TemporaryDirectory(prefix='tc-permission-click-',dir=str(base)) as folder:
 work=Path(folder); ext=work/'ext';shutil.copytree(root/'browser-extension',ext)
 profile=work/'profile'
 log=(work/'chrome.log').open('wb')
 proc=subprocess.Popen(['chromium','--no-sandbox','--disable-gpu','--disable-dev-shm-usage',
   '--no-first-run','--no-default-browser-check','--remote-debugging-port=0',
   '--remote-allow-origins=*','--user-data-dir='+str(profile),
   '--disable-extensions-except='+str(ext),'--load-extension='+str(ext),
   'about:blank'],stdout=log,stderr=log,preexec_fn=os.setsid)
 ws=None
 try:
  for i in range(55):
   if (profile/'DevToolsActivePort').is_file():break
   time.sleep(.2)
  debug=profile/'DevToolsActivePort'
  if not debug.is_file(): raise RuntimeError('debug missing')
  port=int(debug.read_text().splitlines()[0]); worker=None; page=None
  for i in range(75):
   targets=get_json('http://127.0.0.1:%d/json'%port)
   workers=[x for x in targets if x.get('type')=='service_worker' and x.get('url','').endswith('companion_worker.mjs')]
   pages=[x for x in targets if x.get('type')=='page']
   if workers and pages:
    worker=workers[0];page=pages[0];break
   time.sleep(.2)
  if worker is None:raise RuntimeError('no worker')
  extid=urlsplit(worker['url']).hostname
  print('EXTID',extid,flush=True)
  import websocket
  ws=websocket.create_connection(page['webSocketDebuggerUrl'], timeout=12,suppress_origin=True)
  cdp(ws,'Page.enable')
  cdp(ws,'Page.navigate',{'url':'chrome-extension://%s/popup.html'%extid})
  for i in range(50):
   try:
    ready=evaluate(ws,'document.readyState==="complete" && typeof chrome!=="undefined" && typeof chrome.permissions!=="undefined"')
    if ready:break
   except:pass
   time.sleep(.2)
  print('READY',ready,flush=True)
  result=evaluate(ws,'''(async()=>{
   document.getElementById('companion-origin').value='https://www.adafruit.com/product/1083';
   const button=document.getElementById('companion-grant');
   button.scrollIntoView({block:'center'});
   await new Promise(r=>setTimeout(r,180));
   const b=button.getBoundingClientRect();
   return {x:(b.left+b.right)/2,y:(b.top+b.bottom)/2,
     before:await chrome.permissions.contains({origins:['https://www.adafruit.com/*']}),
     viewport:{w:innerWidth,h:innerHeight}};
  })()''')
  print('BEFORE',result,flush=True)
  x,y=result['x'],result['y']
  cdp(ws,'Input.dispatchMouseEvent',{'type':'mousePressed','x':x,'y':y,'button':'left','clickCount':1})
  cdp(ws,'Input.dispatchMouseEvent',{'type':'mouseReleased','x':x,'y':y,'button':'left','clickCount':1})
  # Test-only X11 input to the native Chromium permission prompt.
  # Its layout is fixed by the Xvfb screen size; check the browser API
  # after every simulated click to ensure we didn't miss the button.
  import ctypes
  time.sleep(2.7)
  libx=ctypes.cdll.LoadLibrary("libX11.so.6")
  libtest=ctypes.cdll.LoadLibrary("libXtst.so.6")
  libx.XOpenDisplay.restype=ctypes.c_void_p
  xdisplay=libx.XOpenDisplay(os.environ["DISPLAY"].encode())
  assert xdisplay
  libtest.XTestFakeMotionEvent.argtypes=[ctypes.c_void_p,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_ulong]
  libtest.XTestFakeButtonEvent.argtypes=[ctypes.c_void_p,ctypes.c_uint,ctypes.c_int,ctypes.c_ulong]
  libtest.XTestFakeMotionEvent(xdisplay,-1,625,289,0)
  libtest.XTestFakeButtonEvent(xdisplay,1,1,0)
  libtest.XTestFakeButtonEvent(xdisplay,1,0,0)
  libx.XFlush.argtypes=[ctypes.c_void_p];libx.XFlush(xdisplay)
  libx.XCloseDisplay.argtypes=[ctypes.c_void_p];libx.XCloseDisplay(xdisplay)
  print("NATIVE DIALOG DENY FIRST REQUEST",flush=True)
  for i in range(7):
   time.sleep(.4)
   data=evaluate(ws,'''(async()=>({granted:await chrome.permissions.contains({origins:['https://www.adafruit.com/*']}),
              label:document.getElementById('companion-status')?.textContent,
              focus:document.hasFocus()}))()''')
   print('POLL',i,data,flush=True)
   if 'declined' in (data.get('label') or ''): break
  assert data['granted'] is False and 'declined' in data['label'], 'USER_DENIAL_FAILED'
  print("INITIAL_NATIVE_DENIAL_OK",flush=True)
  rect=evaluate(ws,'''(()=>{
    const b=document.getElementById("companion-grant");
    b.scrollIntoView({block:"center"});
    const r=b.getBoundingClientRect();
    return {x:(r.left+r.right)/2,y:(r.top+r.bottom)/2};
  })()''')
  cdp(ws,'Input.dispatchMouseEvent',{'type':'mousePressed','x':rect['x'],'y':rect['y'],'button':'left','clickCount':1})
  cdp(ws,'Input.dispatchMouseEvent',{'type':'mouseReleased','x':rect['x'],'y':rect['y'],'button':'left','clickCount':1})
  time.sleep(2.8)
  xdisplay=libx.XOpenDisplay(os.environ["DISPLAY"].encode())
  libtest.XTestFakeMotionEvent(xdisplay,-1,705,289,0)
  libtest.XTestFakeButtonEvent(xdisplay,1,1,0)
  libtest.XTestFakeButtonEvent(xdisplay,1,0,0)
  libx.XFlush(xdisplay);libx.XCloseDisplay(xdisplay)
  time.sleep(.6)
  accepted=evaluate(ws,'''(async()=>({
    granted:await chrome.permissions.contains({origins:['https://www.adafruit.com/*']}),
    label:document.getElementById('companion-status')?.textContent,
  }))()''')
  print("ACCEPTED",accepted,flush=True)
  assert accepted['granted'] is True and 'Permission granted' in accepted['label']
  rect=evaluate(ws,'''(()=>{
    const b=document.getElementById("companion-revoke");
    b.scrollIntoView({block:"center"});
    const r=b.getBoundingClientRect();
    return {x:(r.left+r.right)/2,y:(r.top+r.bottom)/2};
  })()''')
  cdp(ws,'Input.dispatchMouseEvent',{'type':'mousePressed','x':rect['x'],'y':rect['y'],'button':'left','clickCount':1})
  cdp(ws,'Input.dispatchMouseEvent',{'type':'mouseReleased','x':rect['x'],'y':rect['y'],'button':'left','clickCount':1})
  time.sleep(.5)
  revoked=evaluate(ws,'''(async()=>({
    granted:await chrome.permissions.contains({origins:['https://www.adafruit.com/*']}),
    label:document.getElementById('companion-status')?.textContent,
  }))()''')
  print('REVOKED',revoked,flush=True)
  assert revoked['granted'] is False and 'Access disabled' in revoked['label']
  # Confirm revocation also blocks queued browser research in the REAL
  # service worker, without any new request to the merchant origin.
  with local_broker() as broker:
   job=enqueue_http(broker,target)
   settings={"enabled":True,"port":broker.server_port,
             "token":broker.companion.token}
   configured=evaluate(ws,'''(async()=>{
      await chrome.storage.local.set({companionConfig:SETTINGS});
      return await chrome.runtime.sendMessage({action:"configureCompanion"});
   })()'''.replace("SETTINGS",json.dumps(settings)))
   assert configured=={"ok":True},configured
   row=wait_job(broker,job)
   assert row["status"]=="SITE_PERMISSION_REQUIRED",row["status"]
   assert row["result"] is None
   print('POST_REVOKE_QUEUE_BLOCKED',row["status"],flush=True)
  print('REAL_NATIVE_CHROMIUM_DENY_GRANT_REVOKE_PASS',flush=True)
 finally:
  if ws:ws.close()
  try:os.killpg(proc.pid,signal.SIGTERM)
  except ProcessLookupError:pass
  try:proc.wait(timeout=5)
  except subprocess.TimeoutExpired:os.killpg(proc.pid,signal.SIGKILL)
  log.close()
  time.sleep(.25)
