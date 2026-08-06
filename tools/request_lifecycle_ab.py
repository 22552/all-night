import asyncio
import importlib.util
import pathlib
import statistics
import subprocess
import sys
import tempfile
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent


def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod

main_text = subprocess.check_output(['git', 'show', 'origin/main:night.py'], text=True)
with tempfile.NamedTemporaryFile('w', suffix='.py', delete=False) as f:
    f.write(main_text)
    main_path = pathlib.Path(f.name)

base = load_module(main_path, 'night_main_ab')
opt = load_module(ROOT / 'night.py', 'night_opt_ab')

scope = {'type':'http','method':'GET','path':'/','query_string':b'','headers':[]}
async def receive(): return {'type':'http.request','body':b'','more_body':False}
async def send(_): pass

def bench_request(mod, n=300000):
    cls = mod.Request
    t0=time.perf_counter_ns()
    for _ in range(n): cls(scope=scope, receive=receive, send=send)
    return (time.perf_counter_ns()-t0)/n

async def make_app(mod):
    app=mod.Night()
    @app.get('/')
    def index(): return 'ok'
    return app

async def bench_app(mod, n=20000):
    app = await make_app(mod)
    async def one():
        events=[]
        async def recv(): return {'type':'http.request','body':b'','more_body':False}
        async def snd(e): events.append(e)
        await app(scope, recv, snd)
    for _ in range(500): await one()
    t0=time.perf_counter_ns()
    for _ in range(n): await one()
    return (time.perf_counter_ns()-t0)/n

async def main():
    rq0=bench_request(base); rq1=bench_request(opt)
    app0=await bench_app(base); app1=await bench_app(opt)
    print(f'Request init main={rq0:.1f} ns opt={rq1:.1f} ns speedup={rq0/rq1:.3f}x')
    print(f'ASGI GET    main={app0:.1f} ns opt={app1:.1f} ns speedup={app0/app1:.3f}x')

asyncio.run(main())
