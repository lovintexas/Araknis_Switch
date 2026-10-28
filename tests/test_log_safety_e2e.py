"""End-to-end: dummy credentials, DEBUG level, real framework file handler.

A fake Araknis switch (local HTTP server, real RSA login handshake) hands out a
session token in a cookie, a header and the JSON body.  The real poeport client
talks to it while the framework's real shared log handler -- pointed at a temp
file -- records everything at DEBUG.  Afterwards the log file must contain none
of: the password, the session token, the encrypted login values, the username.
"""
import base64
import contextlib
import http.client
import importlib
import json
import logging
import os
import subprocess
import sys
import threading
import time
import types
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, quote_plus

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import pytest  # noqa: E402
from cryptography.hazmat.primitives import serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import padding, rsa  # noqa: E402

import logsafe  # noqa: E402
import poeport  # noqa: E402
import udi_interface  # noqa: E402
from udi_interface import interface as fw_interface  # noqa: E402
from udi_interface.polylogger import LOG_HANDLER  # noqa: E402

DUMMY_USER = 'dummyuser'
DUMMY_PW = 'Zz9!dummy"pw\'&x=1'
SESSION_TOKEN = 'sess-7f3a9c0e5b1d4a68'

POE = {'poe_port': {'port': [
    {'po': 1, 'en': 1, 'pr': 0, 'cl': 1, 'st': 2, 'err': 4, 'vol': 836, 'amp': 88, 'tem': 200, 'ppw': 47, 'pdc': 4},
    {'po': 2, 'en': 0, 'pr': 0, 'cl': 1, 'st': 0, 'err': 1, 'vol': 0, 'amp': 0, 'tem': 199, 'ppw': 0, 'pdc': 0},
]}}
CFG = {'port_cfg': {'port': [
    {'po': 1, 'na': 'My Camera', 'en': 1, 'up': 1, 'sp': 100, 'dp': 1},
    {'po': 2, 'na': 'Port 2', 'en': 1, 'up': 0, 'sp': 1000, 'dp': 1},
]}}
GLOB = {'poe_global': {'pb': 375, 'ap': 235}}
DATA = {'poe_port': POE, 'port_cfg': CFG, 'poe_global': GLOB}


class FakeSwitch:
    def __init__(self):
        self.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.pem = self.key.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
        self.expire_next = False
        self.ciphertexts = []      # raw base64 values the client posted at login
        self.posts = []
        self.logins = []
        sw = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, obj, headers=None):
                body = json.dumps(obj).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(body)))
                for k, v in (headers or {}).items():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                if self.path == '/conf/key':
                    body = sw.pem.encode()
                    self.send_response(200)
                    self.send_header('Content-Length', str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                ep = self.path.split('?', 1)[1]
                if sw.expire_next and ep in DATA:
                    sw.expire_next = False
                    return self._send({'result': 2})
                if ep in DATA:
                    return self._send(dict(DATA[ep], result=0))
                return self._send({'result': 0})

            def do_POST(self):
                n = int(self.headers.get('Content-Length', 0))
                form = parse_qs(self.rfile.read(n).decode())
                ep = self.path.split('?', 1)[1]
                if ep == 'login':
                    u_enc, p_enc = form['etvapqp'][0], form['rctater'][0]
                    sw.ciphertexts += [u_enc, p_enc]
                    dec = lambda v: sw.key.decrypt(base64.b64decode(v), padding.PKCS1v15()).decode()
                    ok = (dec(u_enc), dec(p_enc)) == (DUMMY_USER, DUMMY_PW)
                    sw.logins.append(ok)
                    if ok:
                        return self._send({'result': 0, 'sessionid': SESSION_TOKEN},
                                          {'Set-Cookie': 'sessionid=%s; Path=/' % SESSION_TOKEN,
                                           'X-Session-Token': SESSION_TOKEN})
                    return self._send({'result': 1, 'msg': 'invalid account'})
                sw.posts.append((ep, form))
                return self._send({'result': 0})

        self.httpd = ThreadingHTTPServer(('127.0.0.1', 0), H)
        self.host = '127.0.0.1:%d' % self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture(scope='module')
def switch():
    sw = FakeSwitch()
    yield sw
    sw.close()


class PluginLog:
    """The framework's real shared handler, redirected to a temp file, at DEBUG."""

    def __init__(self, path):
        self.path = str(path)
        self.handler = LOG_HANDLER.handler

    def text(self):
        self.handler.flush()
        with open(self.path, encoding='utf-8') as f:
            return f.read()


@pytest.fixture
def plog(tmp_path):
    h = LOG_HANDLER.handler
    old_path = h.baseFilename
    h.close()                                   # next emit reopens at the new path
    h.baseFilename = str(tmp_path / 'debug.log')
    names = ['udi_interface', 'udi_interface.interface', 'urllib3']
    old_levels = {n: logging.getLogger(n).level for n in names}
    for n in names:
        logging.getLogger(n).setLevel(logging.DEBUG)
    logsafe.clear_secrets()
    logsafe.install()
    open(h.baseFilename, 'a').close()
    try:
        yield PluginLog(h.baseFilename)
    finally:
        for n, lvl in old_levels.items():
            logging.getLogger(n).setLevel(lvl)
        logsafe.clear_secrets()
        logsafe.install()
        h.close()
        h.baseFilename = old_path


@contextlib.contextmanager
def wire_debug():
    """Worst case: http.client prints raw requests/headers (incl. login body, cookies).
    Under a real plugin run sys.stdout is udi_interface's LoggerWriter -> LOGGER.debug."""
    writer = importlib.import_module('udi_interface.udi_interface').LoggerWriter
    old = http.client.HTTPConnection.debuglevel
    http.client.HTTPConnection.debuglevel = 1
    try:
        with contextlib.redirect_stdout(writer(udi_interface.LOGGER.debug)):
            yield
    finally:
        http.client.HTTPConnection.debuglevel = old


def assert_clean(log_text, switch=None):
    assert DUMMY_PW not in log_text
    for variant in (quote(DUMMY_PW, safe=''), quote_plus(DUMMY_PW), json.dumps(DUMMY_PW)[1:-1], repr(DUMMY_PW)[1:-1]):
        assert variant not in log_text
    assert SESSION_TOKEN not in log_text
    assert DUMMY_USER not in log_text
    for c in (switch.ciphertexts if switch else []):
        assert c not in log_text and quote(c, safe='') not in log_text and quote_plus(c) not in log_text


def run_session(switch):
    """What the plugin does: log in, read the switch, change a port, survive a session expiry."""
    c = poeport.make_client(switch.host, DUMMY_USER, DUMMY_PW)
    data = poeport.fetch_all(c)
    assert data['ports'][1]['watts'] == 4.7
    poeport.api_post(c, 'poe_port_setting', poeport.build_body(c, 1, [-1, -1, -1, 1]))
    switch.expire_next = True
    poeport.fetch_all(c)
    return c


# ---------------------------------------------------------------------------------------

def test_normal_operation_at_debug_logs_no_secrets_but_keeps_diagnostics(plog, switch):
    run_session(switch)
    out = plog.text()
    assert_clean(out, switch)
    for expected in ('logged in to %s' % switch.host.split(':')[0],
                     'GET /conf/key -> HTTP 200',
                     'login POST -> HTTP 200',
                     'login result=0',
                     'GET poe_port -> HTTP 200',
                     'POST poe_port_setting -> HTTP 200',
                     'session expired on'):
        assert expected in out, expected


def test_worst_case_wire_level_debug_is_scrubbed(plog, switch):
    """http.client debug output contains the raw login body and Set-Cookie header."""
    with wire_debug():
        run_session(switch)
    out = plog.text()
    assert 'send:' in out and 'header:' in out          # the raw wire data really was logged...
    assert logsafe.REDACTED in out                       # ...and was scrubbed
    assert_clean(out, switch)


def test_control_without_the_filter_the_same_session_does_leak(plog, switch):
    """Guards against a vacuous pass: with the filter detached the harness DOES see the secrets."""
    h = LOG_HANDLER.handler
    h.removeFilter(logsafe._filter)
    try:
        with wire_debug():
            run_session(switch)
        raw = plog.text()
    finally:
        logsafe.install()
    assert SESSION_TOKEN in raw
    assert any(c in raw or quote_plus(c) in raw or quote(c, safe='') in raw for c in switch.ciphertexts)


def test_rejected_login_and_backoff_do_not_log_the_password(plog, switch):
    c = poeport.make_client(switch.host, DUMMY_USER, DUMMY_PW + 'WRONG')
    for _ in range(2):                                    # 2nd attempt hits the 5-minute backoff
        try:
            poeport.fetch_all(c)
        except Exception as ex:                           # logged exactly as plugin.py does
            udi_interface.LOGGER.error('Araknis: cannot read switch: %s', ex)
            udi_interface.LOGGER.exception('traceback follows')
    out = plog.text()
    assert 'switch rejected the login (result 1 invalid account)' in out
    assert 'login suppressed for' in out
    assert DUMMY_PW + 'WRONG' not in out and DUMMY_PW not in out and DUMMY_USER not in out


def test_unreachable_switch_failure_is_logged_with_host_and_port(plog):
    c = poeport.make_client('127.0.0.1:9', DUMMY_USER, DUMMY_PW)     # discard port: refused
    try:
        poeport.fetch_all(c)
    except Exception as ex:
        udi_interface.LOGGER.warning('Araknis poll failed: %s', ex)
    out = plog.text()
    assert 'Araknis poll failed' in out and '127.0.0.1' in out
    assert DUMMY_PW not in out and DUMMY_USER not in out


@pytest.mark.parametrize('register_password_first', [False, True])
def test_framework_logs_of_the_pg3_config_message_are_scrubbed(plog, monkeypatch, register_password_first):
    """Drives udi_interface's real Interface._handleInput, which logs the whole PG3 message.
    False = the first message, before the plugin knows the password (pattern-only redaction)."""
    if register_password_first:
        logsafe.add_secret(DUMMY_PW)
    monkeypatch.setattr(fw_interface.pub, 'publish', lambda *a, **k: None)
    stub = types.SimpleNamespace(**{n: n for n in (
        'CUSTOMPARAMS', 'CUSTOMDATA', 'CUSTOMTYPEDDATA', 'CUSTOMTYPEDPARAMS', 'NOTICES', 'CUSTOMNS',
        'ISY', 'NSINFO', 'DISCOVER', 'OAUTH', 'CUSTOMPARAMSDOC')})
    cfg = {'host': '192.0.2.10', 'username': DUMMY_USER, 'password': DUMMY_PW}
    messages = [
        ('custom', {'customparams': json.dumps(cfg)}),
        ('getAll', {'key': 'customparams', 'value': json.dumps(cfg)}),
        ('config', {'customparams': cfg, 'logLevel': 'DEBUG'}),
    ]
    for key, item in messages:
        try:
            fw_interface.Interface._handleInput(stub, key, item, None)
        except Exception:
            pass                                          # the stub may trip later; the log line is already written
    out = plog.text()
    assert out.count('PROCESS ') == 3                     # the framework really did log all three
    assert '192.0.2.10' in out                            # non-secret content kept
    assert DUMMY_PW not in out and DUMMY_USER not in out
    assert logsafe.REDACTED in out


def test_print_and_traceback_output_goes_through_the_filter(plog):
    """Under a real run (python3 main.py) udi_interface swaps sys.stdout/stderr for log writers."""
    writer = importlib.import_module('udi_interface.udi_interface').LoggerWriter
    logsafe.add_secret(DUMMY_PW)
    with contextlib.redirect_stdout(writer(udi_interface.LOGGER.debug)):
        print('debug dump:', {'username': DUMMY_USER, 'password': DUMMY_PW, 'cookie': SESSION_TOKEN})
    with contextlib.redirect_stderr(writer(udi_interface.LOGGER.error)):
        try:
            raise RuntimeError('failed with password=%s token=%s' % (DUMMY_PW, SESSION_TOKEN))
        except RuntimeError:
            import traceback
            traceback.print_exc()
    out = plog.text()
    assert 'debug dump' in out and 'RuntimeError' in out
    assert_clean(out)


def test_importing_plugin_installs_the_filter_before_any_interface_exists(tmp_path):
    """main.py imports plugin.py before it constructs udi_interface.Interface(), so the filter must
    already be on the framework's handler right after that import."""
    code = (
        "import sys\n"
        "sys.path.insert(0, %r)\n"
        "import plugin, logsafe\n"
        "from udi_interface.polylogger import LOG_HANDLER\n"
        "import udi_interface.interface as i\n"
        "print('FILTER_ON_HANDLER', logsafe._filter in LOG_HANDLER.handler.filters)\n"
    ) % ROOT
    res = subprocess.run([sys.executable, '-c', code], cwd=str(tmp_path), capture_output=True,
                         text=True, timeout=120)
    assert 'FILTER_ON_HANDLER True' in res.stdout, res.stdout + res.stderr
