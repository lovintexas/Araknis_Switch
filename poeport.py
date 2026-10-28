"""Araknis 310-series web-API client plus the per-port node.

The switch has no documented API. This talks to the same JSON CGI its own web
page uses (/cgi-bin/datajson.cgi). Login: GET /conf/key returns an RSA public
key; username and password are each RSA (PKCS#1 v1.5) encrypted, base64
encoded and POSTed as 'etvapqp' / 'rctater' to ?login.  The session is tied to
the client IP (no cookie).  A JSON 'result' of 0 is success, 2 is an expired
session, 9 is a lockout.
"""
import base64
import json
import threading
import time

import requests
import udi_interface
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import padding

LOGGER = udi_interface.LOGGER
Node = udi_interface.Node

LOGIN_BACKOFF_S = 300
SPEED_MAP = {10: 1, 100: 2, 1000: 3}
DELIVERING = (2, 6)  # 2 = Delivering, 6 = Requesting power


def make_client(host, username, password):
    return {
        'host': (host or '').strip(),
        'user': username or '',
        'pw': password or '',
        's': requests.Session(),
        'lock': threading.RLock(),
        'logged_in': False,
        'next_login': 0.0,
        'rowmap': {},
    }


def _login(c):
    now = time.time()
    if now < c['next_login']:
        raise RuntimeError('login suppressed for %d more seconds after a rejected login'
                           % int(c['next_login'] - now))
    base = 'http://%s' % c['host']
    s = c['s']
    r = s.get(base + '/conf/key', timeout=10)
    r.raise_for_status()
    pub = serialization.load_pem_public_key(r.text.strip().encode())

    def enc(v):
        return base64.b64encode(pub.encrypt(v.encode(), padding.PKCS1v15())).decode()

    r = s.post(base + '/cgi-bin/datajson.cgi?login',
               data={'etvapqp': enc(c['user']), 'rctater': enc(c['pw'])}, timeout=20)
    j = json.loads(r.text)
    if j.get('result') != 0:
        c['next_login'] = now + LOGIN_BACKOFF_S
        c['logged_in'] = False
        raise RuntimeError('switch rejected the login (result %s %s)' % (j.get('result'), j.get('msg', '')))
    c['logged_in'] = True
    LOGGER.info('Araknis: logged in to %s', c['host'])


def _call(c, method, endpoint, body=None):
    with c['lock']:
        for _attempt in (0, 1):
            if not c['logged_in']:
                _login(c)
            url = 'http://%s/cgi-bin/datajson.cgi?%s' % (c['host'], endpoint)
            if method == 'GET':
                r = c['s'].get(url, timeout=20)
            else:
                r = c['s'].post(url, data=body, timeout=30)
            j = json.loads(r.text)
            if j.get('result') == 2:  # session expired
                c['logged_in'] = False
                continue
            if j.get('result') != 0:
                raise RuntimeError('switch returned result=%s msg=%s for %s'
                                   % (j.get('result'), j.get('msg', ''), endpoint))
            return j
    raise RuntimeError('switch session keeps expiring')


def api_get(c, endpoint):
    return _call(c, 'GET', endpoint)


def api_post(c, endpoint, body):
    return _call(c, 'POST', endpoint, body)


def api_logout(c):
    try:
        if c.get('logged_in'):
            c['s'].get('http://%s/cgi-bin/datajson.cgi?logout' % c['host'], timeout=5)
    except Exception:
        pass
    c['logged_in'] = False


def fetch_all(c):
    """Read PoE, link and global PoE data. Returns {'ports': {n: {...}}, 'total': W, 'budget': W}."""
    poe = api_get(c, 'poe_port').get('poe_port')
    if not isinstance(poe, dict) or not isinstance(poe.get('port'), list):
        raise RuntimeError('switch returned no PoE port data')
    poe = poe['port']
    cfg = api_get(c, 'port_cfg').get('port_cfg') or {}
    cfg = {p['po']: p for p in (cfg.get('port') or [])}
    glob = api_get(c, 'poe_global').get('poe_global') or {}
    c['rowmap'] = {p['po']: i + 1 for i, p in enumerate(poe)}
    ports = {}
    for p in poe:
        po = p['po']
        link = cfg.get(po, {})
        speed = 0
        if link.get('up') == 1 and link.get('en', 1) == 1:
            speed = SPEED_MAP.get(link.get('sp'), 0)
        live = p.get('st') in DELIVERING
        ports[po] = {
            'name': link.get('na') or '',
            'en': 1 if p.get('en') else 0,
            'st': int(p.get('st', 0)),
            'speed': speed,
            # Same scaling the switch's own web page uses.
            'watts': round(p.get('ppw', 0) / 10.0, 1) if live else 0,
            'volts': round(p.get('vol', 0) * 64.45 / 1000.0, 1) if live else 0,
            'ma': p.get('amp', 0) if live else 0,
        }
    return {'ports': ports,
            'total': round(glob.get('ap', 0) / 10.0, 1),
            'budget': glob.get('pb', 0)}


def build_body(c, port, vals):
    """vals = [enable, power_class, priority, cycle]; -1 means leave unchanged."""
    row = c.get('rowmap', {}).get(port, port)
    return 'p%d=%s&' % (row, ','.join(str(v) for v in vals))


def apply_all(ports, summary, data):
    for po, node in list(ports.items()):
        node.apply(data['ports'].get(po))
    if summary is not None:
        summary.apply(data)


class PoePort(Node):
    id = 'poeport'
    drivers = [
        {'driver': 'ST', 'value': 0, 'uom': 25, 'name': 'PoE Power'},
        {'driver': 'POE_STATE', 'value': 0, 'uom': 25, 'name': 'PoE State'},
        {'driver': 'LINK_SPEED', 'value': 0, 'uom': 25, 'name': 'Link'},
        {'driver': 'CPW', 'value': 0, 'uom': 73, 'name': 'PoE Power Used'},
        {'driver': 'CV', 'value': 0, 'uom': 72, 'name': 'PoE Voltage'},
        {'driver': 'CC', 'value': 0, 'uom': 41, 'name': 'PoE Current'},
    ]

    def __init__(self, polyglot, primary, address, name, client, port):
        super().__init__(polyglot, primary, address, name)
        self.client = client
        self.port = port

    def apply(self, d):
        if not d:
            return
        self.setDriver('ST', d['en'])
        self.setDriver('POE_STATE', d['st'])
        self.setDriver('LINK_SPEED', d['speed'])
        self.setDriver('CPW', d['watts'])
        self.setDriver('CV', d['volts'])
        self.setDriver('CC', d['ma'])

    def refresh(self):
        data = fetch_all(self.client)
        self.apply(data['ports'].get(self.port))

    def change(self, vals, settle=2.0):
        try:
            api_post(self.client, 'poe_port_setting', build_body(self.client, self.port, vals))
            time.sleep(settle)
            self.refresh()
        except Exception as ex:
            LOGGER.error('Araknis port %s command failed: %s', self.port, ex)

    def poe_on(self, command=None):
        LOGGER.info('Araknis port %s: PoE On', self.port)
        self.change([1, -1, -1, -1])

    def poe_off(self, command=None):
        LOGGER.info('Araknis port %s: PoE Off', self.port)
        self.change([0, -1, -1, -1])

    def poe_cycle(self, command=None):
        try:
            enabled = int(float(self.getDriver('ST')))
        except Exception:
            enabled = 1
        if enabled != 1:
            LOGGER.warning('Araknis port %s: PoE is Off, power cycle ignored', self.port)
            return
        LOGGER.info('Araknis port %s: PoE Power Cycle', self.port)
        self.change([-1, -1, -1, 1], settle=4.0)

    def query(self, command=None):
        try:
            self.refresh()
        except Exception as ex:
            LOGGER.error('Araknis port %s query failed: %s', self.port, ex)
        self.reportDrivers()

    commands = {
        'DON': poe_on,
        'DOF': poe_off,
        'POE_CYCLE': poe_cycle,
        'QUERY': query,
    }
