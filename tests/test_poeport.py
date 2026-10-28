import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import poeport  # noqa: E402

POE = {'poe_port': {'port': [
    {'po': 1, 'en': 1, 'pr': 0, 'cl': 1, 'st': 2, 'err': 4, 'vol': 836, 'amp': 88, 'tem': 200, 'ppw': 47, 'pdc': 4},
    {'po': 2, 'en': 1, 'pr': 0, 'cl': 1, 'st': 1, 'err': 1, 'vol': 0, 'amp': 0, 'tem': 199, 'ppw': 0, 'pdc': 0},
    {'po': 3, 'en': 0, 'pr': 0, 'cl': 1, 'st': 0, 'err': 1, 'vol': 0, 'amp': 0, 'tem': 199, 'ppw': 0, 'pdc': 0},
]}}
CFG = {'port_cfg': {'port': [
    {'po': 1, 'na': 'My Camera', 'en': 1, 'up': 1, 'sp': 100, 'dp': 1},
    {'po': 2, 'na': 'Port 2', 'en': 1, 'up': 0, 'sp': 1000, 'dp': 1},
    {'po': 3, 'na': '', 'en': 0, 'up': 0, 'sp': 1000, 'dp': 1},
]}}
GLOB = {'poe_global': {'pb': 375, 'ap': 235}}


def fake_get(c, endpoint):
    return {'poe_port': POE, 'port_cfg': CFG, 'poe_global': GLOB}[endpoint] if False else (
        POE if endpoint == 'poe_port' else CFG if endpoint == 'port_cfg' else GLOB)


def test_fetch_all_scaling(monkeypatch):
    monkeypatch.setattr(poeport, 'api_get', fake_get)
    c = poeport.make_client('1.2.3.4', 'u', 'p')
    d = poeport.fetch_all(c)
    p1 = d['ports'][1]
    assert p1['watts'] == 4.7
    assert p1['volts'] == 53.9
    assert p1['ma'] == 88
    assert p1['speed'] == 2          # 100 Mbps
    assert p1['name'] == 'My Camera'
    assert d['ports'][2]['watts'] == 0 and d['ports'][2]['speed'] == 0
    assert d['ports'][3]['en'] == 0 and d['ports'][3]['st'] == 0
    assert d['total'] == 23.5
    assert d['budget'] == 375
    assert c['rowmap'] == {1: 1, 2: 2, 3: 3}


def test_build_body():
    c = poeport.make_client('1.2.3.4', 'u', 'p')
    c['rowmap'] = {23: 23}
    assert poeport.build_body(c, 23, [0, -1, -1, -1]) == 'p23=0,-1,-1,-1&'
    assert poeport.build_body(c, 23, [-1, -1, -1, 1]) == 'p23=-1,-1,-1,1&'


def test_no_poe_data_raises(monkeypatch):
    monkeypatch.setattr(poeport, 'api_get', lambda c, e: {'poe_port': ''})
    c = poeport.make_client('1.2.3.4', 'u', 'p')
    try:
        poeport.fetch_all(c)
    except RuntimeError:
        return
    raise AssertionError('expected RuntimeError')
