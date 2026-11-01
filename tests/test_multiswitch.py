from unittest.mock import MagicMock, patch
from plugin import Controller


def test_two_switch_discovery():
    ctl = Controller.__new__(Controller)
    ctl.poly = MagicMock()
    ctl.setDriver = MagicMock()
    ctl.poly.getValidAddress.side_effect = lambda x: x
    ctl.poly.getValidName.side_effect = lambda x: x
    ctl.address = 'ctl'
    ctl._cfg = {
        'host': '192.168.1.10',
        'username': 'admin',
        'password': 'test1',
        'host2': '192.168.1.11',
        'username2': 'admin',
        'password2': 'test2',
    }
    ctl._switches = {}
    ctl._switch_lock = __import__('threading').RLock()

    data = {
        'ports': {1: {'name': 'Camera'}, 2: {'name': 'Access Point'}},
        'total': 20,
        'budget': 120,
    }

    with patch('poeport.make_client', side_effect=lambda *a: MagicMock()), \
         patch('poeport.fetch_all', return_value=data), \
         patch('poeport.PoePort') as port_cls, \
         patch('poesummary.PoeSummary') as summary_cls, \
         patch('poeport.apply_all'), \
         patch('time.sleep'):

        ctl.discover()

        assert set(ctl._switches) == {1, 2}

        addresses = [call.args[2] for call in port_cls.call_args_list]
        assert addresses == [
            'port1', 'port2',
            'sw2port1', 'sw2port2'
        ]

        summaries = [call.args[2] for call in summary_cls.call_args_list]
        assert summaries == ['summary', 'sw2summary']


def test_independent_polling():
    ctl = Controller.__new__(Controller)
    ctl.poly = MagicMock()
    ctl.setDriver = MagicMock()
    ctl._switch_lock = __import__('threading').RLock()

    client1 = MagicMock()
    client2 = MagicMock()

    ctl._switches = {
        1: {'client': client1, 'ports': {}, 'summary': None},
        2: {'client': client2, 'ports': {}, 'summary': None},
    }

    data = {'ports': {}, 'total': 20, 'budget': 120}

    def fake_fetch(client):
        if client is client2:
            raise RuntimeError('Switch 2 offline')
        return data

    with patch('poeport.fetch_all', side_effect=fake_fetch), \
         patch('poeport.apply_all') as apply:
        ctl.shortPoll()

        assert apply.call_count == 1
        assert apply.call_args.args[2] == data
        assert 'conn2' in [
            call.args[0]
            for call in ctl.poly.Notices.__setitem__.call_args_list
        ]


def test_switch2_credentials_change():
    import threading

    ctl = Controller.__new__(Controller)
    ctl.poly = MagicMock()
    ctl._switch_lock = threading.RLock()
    ctl._started = True

    client1 = MagicMock()
    client2 = MagicMock()
    new_client2 = MagicMock()

    port1 = MagicMock()
    port2 = MagicMock()

    ctl._cfg = {
        'host': '192.168.1.10',
        'username': 'admin',
        'password': 'test1',
        'host2': '192.168.1.11',
        'username2': 'admin',
        'password2': 'test2',
    }

    ctl._switches = {
        1: {
            'client': client1,
            'ports': {1: port1},
            'summary': MagicMock(),
        },
        2: {
            'client': client2,
            'ports': {1: port2},
            'summary': MagicMock(),
        },
    }

    new_params = dict(ctl._cfg)
    new_params['password2'] = 'newpassword'

    with patch('poeport.make_client', return_value=new_client2), \
         patch('poeport.api_logout') as logout, \
         patch.object(ctl, 'discover'):

        ctl.parameterHandler(new_params)

        assert ctl._switches[1]['client'] is client1
        assert port1.client is not new_client2

        assert ctl._switches[2]['client'] is new_client2
        assert port2.client is new_client2

        logout.assert_called_once_with(client2)
        ctl.poly.delNode.assert_not_called()


def test_remove_switch2():
    import threading

    ctl = Controller.__new__(Controller)
    ctl.poly = MagicMock()
    ctl._switch_lock = threading.RLock()
    ctl._started = True

    client1 = MagicMock()
    client2 = MagicMock()

    port1 = MagicMock()
    port1.address = 'port1'

    port2 = MagicMock()
    port2.address = 'sw2port1'

    summary1 = MagicMock()
    summary1.address = 'summary'

    summary2 = MagicMock()
    summary2.address = 'sw2summary'

    ctl._cfg = {
        'host': '192.168.1.10',
        'username': 'admin',
        'password': 'test1',
        'host2': '192.168.1.11',
        'username2': 'admin',
        'password2': 'test2',
    }

    ctl._switches = {
        1: {
            'client': client1,
            'ports': {1: port1},
            'summary': summary1,
        },
        2: {
            'client': client2,
            'ports': {1: port2},
            'summary': summary2,
        },
    }

    new_params = {
        'host': '192.168.1.10',
        'username': 'admin',
        'password': 'test1',
    }

    with patch('poeport.api_logout') as logout, \
         patch.object(ctl, 'discover'):

        ctl.parameterHandler(new_params)

        assert set(ctl._switches) == {1}
        assert ctl._switches[1]['client'] is client1
        assert ctl._switches[1]['ports'][1] is port1

        logout.assert_called_once_with(client2)

        deleted = [
            call.args[0]
            for call in ctl.poly.delNode.call_args_list
        ]

        assert set(deleted) == {'sw2port1', 'sw2summary'}
        assert 'port1' not in deleted
        assert 'summary' not in deleted


def test_discovery_recovers_after_switch_offline():
    import threading

    ctl = Controller.__new__(Controller)
    ctl.poly = MagicMock()
    ctl.setDriver = MagicMock()
    ctl.poly.getValidAddress.side_effect = lambda x: x
    ctl.poly.getValidName.side_effect = lambda x: x
    ctl.address = 'ctl'
    ctl._switch_lock = threading.RLock()
    ctl._switches = {}
    ctl._started = True
    ctl._cfg = {
        'host': '192.168.1.10',
        'username': 'admin',
        'password': 'test1',
        'host2': '192.168.1.11',
        'username2': 'admin',
        'password2': 'test2',
    }

    data = {
        'ports': {1: {'name': 'Camera'}},
        'total': 10,
        'budget': 120,
    }

    attempts = {}

    def fake_fetch(client):
        host = client['host']
        attempts[host] = attempts.get(host, 0) + 1
        if host == '192.168.1.11' and attempts[host] == 1:
            raise ConnectionError('Switch 2 offline')
        return data

    with patch('poeport.make_client',
               side_effect=lambda host, username, password: {'host': host}), \
         patch('poeport.fetch_all', side_effect=fake_fetch), \
         patch('poeport.PoePort'), \
         patch('poesummary.PoeSummary'), \
         patch('poeport.apply_all'), \
         patch('time.sleep'):

        ctl.discover()

        assert len(ctl._switches[1]['ports']) == 1
        assert len(ctl._switches[2]['ports']) == 0

        ctl.longPoll()

        assert len(ctl._switches[1]['ports']) == 1
        assert len(ctl._switches[2]['ports']) == 1
        assert attempts['192.168.1.11'] == 2
