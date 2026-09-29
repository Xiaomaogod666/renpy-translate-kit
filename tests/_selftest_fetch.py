"""安装辅助脚本的自测: fetch_engine.py 的下载重试 / 解包 / 入口参数。

全部本地跑, 不需要外网 —— 下载用例由本机的临时 HTTP 服务器喂数据,
服务器会故意在响应中途断流, 复现真实网络里的半截包。
跑法:
    <venv>/python.exe tests/_selftest_fetch.py
"""
import hashlib
import http.server
import importlib.util
import os
import shutil
import socketserver
import sys
import tempfile
import threading
import urllib.request
import zipfile

KIT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except AttributeError:
    pass

# 有的机器上开着抓包代理, 它会把断掉的响应重新包装成"完整"响应,
# 让断流测试失真 —— 所以本地测试直连, 不走代理。
urllib.request.install_opener(
    urllib.request.build_opener(urllib.request.ProxyHandler({})))

_passed = 0
_failed = []


def check(name, cond, detail=''):
    global _passed
    if cond:
        _passed += 1
        print('  [OK]   %s' % name)
    else:
        _failed.append(name)
        print('  [FAIL] %s   %s' % (name, detail))


def load(name):
    path = os.path.join(KIT_DIR, name + '.py')
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


fe = load('fetch_engine')

PAYLOAD = bytes(range(256)) * 4096          # 1 MiB, 带内容校验
PAYLOAD_MD5 = hashlib.md5(PAYLOAD).hexdigest()
_state = {'n': 0, 'mode': 'ok'}


class _Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.0'           # 不要自动分块, 才造得出"半截包"

    def log_message(self, *a):
        pass

    def do_GET(self):
        _state['n'] += 1
        short = ((_state['mode'] == 'cut_once' and _state['n'] == 1)
                 or _state['mode'] == 'cut_all')
        body = PAYLOAD[:len(PAYLOAD) // 3] if short else PAYLOAD
        self.send_response(200)
        self.send_header('Content-Length', str(len(PAYLOAD)))
        self.end_headers()
        self.wfile.write(body)
        self.wfile.flush()
        self.close_connection = True


server = socketserver.TCPServer(('127.0.0.1', 0), _Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
URL = 'http://127.0.0.1:%d/payload.bin' % server.server_address[1]

BASE = os.path.join(tempfile.gettempdir(), 'kit_fetch_test')
shutil.rmtree(BASE, ignore_errors=True)
os.makedirs(BASE)


def make_zip(path, entries):
    with zipfile.ZipFile(path, 'w') as zf:
        for name, data in entries.items():
            zf.writestr(name, data)


try:
    print('=== 1. 下载: 断流后重试 ===')
    _state.update(n=0, mode='cut_once')
    dest = os.path.join(BASE, 'a.bin')
    err = fe.download(URL, dest)
    got = ''
    if os.path.exists(dest):
        got = hashlib.md5(open(dest, 'rb').read()).hexdigest()
    check('断流一次后重试拿到完整文件',
          err is None and got == PAYLOAD_MD5, 'err=%r md5=%s' % (err, got))
    check('确实重试了 (2 次请求)', _state['n'] == 2, _state['n'])

    _state.update(n=0, mode='cut_all')
    dest = os.path.join(BASE, 'b.bin')
    err = fe.download(URL, dest, attempts=3)
    check('持续断流时按约定次数失败',
          err is not None and _state['n'] == 3, 'err=%r n=%s' % (err, _state['n']))
    check('失败后不留下半截文件', not os.path.exists(dest))

    print()
    print('=== 2. 下载: zip 完整性校验 ===')
    _state.update(n=0, mode='ok')
    dest = os.path.join(BASE, 'c.bin')
    err = fe.download(URL, dest, attempts=3, verify_zip=True)
    check('不是 zip 的内容被拦下', err is not None, err)
    check('同样重试三次后放弃', _state['n'] == 3, _state['n'])

    good_zip = os.path.join(BASE, 'ok.zip')
    make_zip(good_zip, {'main.py': '# engine\n'})
    check('完好 zip 通过校验', fe._zip_ok(good_zip) is None, fe._zip_ok(good_zip))

    bad_zip = os.path.join(BASE, 'bad.zip')
    with open(bad_zip, 'wb') as f:
        f.write(b'this is not a zip file at all')
    check('坏文件被 _zip_ok 拦下', fe._zip_ok(bad_zip) is not None)

    print()
    print('=== 3. 解包: 剥外层目录 / 缺件报错 ===')
    nested = os.path.join(BASE, 'nested.zip')
    make_zip(nested, {'repo-devp/main.py': '# engine\n',
                      'repo-devp/requirements.txt': 'flask\n'})
    t1 = os.path.join(BASE, 'out_nested')
    err = fe.extract(nested, t1)
    check('codeload 式外层目录被剥掉',
          err is None and os.path.isfile(os.path.join(t1, 'main.py')), err)
    check('requirements.txt 同步就位',
          os.path.isfile(os.path.join(t1, 'requirements.txt')))

    flat = os.path.join(BASE, 'flat.zip')
    make_zip(flat, {'main.py': '# engine\n', 'requirements.txt': 'flask\n'})
    t2 = os.path.join(BASE, 'out_flat')
    err = fe.extract(flat, t2)
    check('顶层就是文件时也能解',
          err is None and os.path.isfile(os.path.join(t2, 'main.py')), err)

    nomain = os.path.join(BASE, 'nomain.zip')
    make_zip(nomain, {'readme.txt': 'hello\n'})
    t3 = os.path.join(BASE, 'out_nomain')
    err = fe.extract(nomain, t3)
    check('缺 main.py 时报错', err is not None and 'main.py' in str(err), err)
    check('报错时不留下半成品目录', not os.path.exists(t3))

    broken = os.path.join(BASE, 'broken.zip')
    with open(broken, 'wb') as f:
        f.write(b'PK\x03\x04' + b'\x00' * 60)
    err = fe.extract(broken, os.path.join(BASE, 'out_broken'))
    check('坏包解不开时报错', err is not None, err)

    print()
    print('=== 4. 入口: 参数与幂等 ===')
    check('无参数返回用法码', fe.main([]) == 2)
    check('--help 返回用法码', fe.main(['--help']) == 2)

    clash = os.path.join(BASE, 'occupied')
    os.makedirs(clash)
    open(os.path.join(clash, 'something.txt'), 'w').close()
    check('目标非空又没有 main.py 时报错', fe.main([clash]) == 1)
    check('报错后没往里乱写东西',
          not os.path.isfile(os.path.join(clash, 'main.py')))

    src = os.path.join(BASE, 'src.zip')
    make_zip(src, {'repo-devp/main.py': '# engine\n',
                   'repo-devp/requirements.txt': 'flask\n'})
    tgt = os.path.join(BASE, 'engine_ok')
    check('从本地 zip 安装成功', fe.main([tgt, src]) == 0)
    check('装完后 main.py 与 requirements.txt 都在',
          os.path.isfile(os.path.join(tgt, 'main.py'))
          and os.path.isfile(os.path.join(tgt, 'requirements.txt')))
    check('再装一次直接成功 (幂等)', fe.main([tgt, src]) == 0)

    missing = os.path.join(BASE, 'no_such.zip')
    check('本地 zip 不存在时报错',
          fe.main([os.path.join(BASE, 'no_dir'), missing]) == 1)

    print()
    print('=== 5. pip 修复脚本: 入口校验 ===')
    fp = load('fetch_pip')
    check('无参数返回用法码', fp.main([]) == 2)
    check('虚拟环境不存在时报错', fp.main([os.path.join(BASE, 'no_venv')]) == 1)
    # 造一个只够骗过"python 在不在"这步的空壳 venv, 走到查 get-pip.py 那一步
    stub = os.path.join(BASE, 'stub_venv', 'Scripts')
    os.makedirs(stub)
    open(os.path.join(stub, 'python.exe'), 'wb').close()
    check('本地 get-pip.py 不存在时报错',
          fp.main([os.path.dirname(stub), missing]) == 1,
          '缺文件时应该报错而不是继续跑')
finally:
    server.shutdown()
    shutil.rmtree(BASE, ignore_errors=True)

print()
print('总计: %d 通过, %d 失败' % (_passed, len(_failed)))
if _failed:
    print('失败: %s' % ', '.join(_failed))
sys.exit(0 if not _failed else 1)
