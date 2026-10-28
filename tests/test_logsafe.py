"""Unit tests for logsafe.RedactingFilter / redact()."""
import io
import json
import logging
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402

import logsafe  # noqa: E402

PW = 'Zz9!dummy"pw\'&x=1'      # deliberately awkward: both quote types, &, =, !
USER = 'dummyuser'
TOKEN = 'tok-0123456789abcdef'


@pytest.fixture(autouse=True)
def _clean_secrets():
    logsafe.clear_secrets()
    yield
    logsafe.clear_secrets()


def make_logger(name='araknis_logsafe_test.child'):
    """A logger whose own handler carries the filter, writing to a buffer."""
    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    handler.setFormatter(logging.Formatter('%(name)s %(levelname)s %(message)s'))
    logger = logging.getLogger(name)
    logger.handlers = [handler]
    logger.propagate = False
    logger.setLevel(logging.DEBUG)
    logsafe.install()
    assert logsafe._filter in handler.filters
    return logger, buf


# ---- message shapes -------------------------------------------------------------

def test_args_style_message_is_redacted():
    log, buf = make_logger()
    log.info('config is %s', {'host': '10.0.0.5', 'username': USER, 'password': 'hunter22'})
    out = buf.getvalue()
    assert 'hunter22' not in out and USER not in out
    assert "'host': '10.0.0.5'" in out          # unrelated content is kept
    assert logsafe.REDACTED in out


def test_preformatted_string_message_is_redacted():
    """udi_interface logs 'PROCESS ... {}'.format(item): a plain string, no args."""
    log, buf = make_logger()
    item = {'customparams': json.dumps({'host': '10.0.0.5', 'username': USER, 'password': 'hunter22'})}
    log.debug('PROCESS {} message {} from Polyglot'.format('custom', item))
    out = buf.getvalue()
    assert 'hunter22' not in out and USER not in out
    assert 'PROCESS custom message' in out and '10.0.0.5' in out


def test_percent_sign_in_a_redacted_message_does_not_break_formatting():
    log, buf = make_logger()
    log.info('battery 100%% password=hunter22 done %s', 'ok')
    out = buf.getvalue()
    assert 'hunter22' not in out and '100%' in out and 'done ok' in out


@pytest.mark.parametrize('text', [
    '{"host": "h", "username": "%(u)s", "password": "hunter22"}',
    "{'host': 'h', 'username': '%(u)s', 'password': 'hunter22'}",
    # JSON nested inside a JSON string, as PG3 delivers customparams
    '{"customparams": "{\\"username\\": \\"%(u)s\\", \\"password\\": \\"hunter22\\"}"}',
    "{'customparams': '{\"username\": \"%(u)s\", \"password\": \"hunter22\"}'}",
    'username=%(u)s&password=hunter22&host=h',
    'password: hunter22',
    'PASSWORD = "hunter22"',
    "{'password': 12345678}",
    "{'client': {'pw': 'hunter22', 'user': '%(u)s'}}",
])
def test_config_shapes(text):
    log, buf = make_logger()
    log.debug(text % {'u': USER} if '%(u)s' in text else text)
    out = buf.getvalue()
    assert 'hunter22' not in out and '12345678' not in out and USER not in out


def test_password_with_quotes_and_escapes_in_nested_json():
    logsafe.add_secret(PW)
    log, buf = make_logger()
    inner = json.dumps({'username': USER, 'password': PW})
    log.debug('PROCESS custom message {} from Polyglot'.format({'customparams': inner}))
    log.debug('as json string: %s', json.dumps({'customparams': inner}))
    out = buf.getvalue()
    assert PW not in out and 'dummy' not in out.replace('dummyuser', '')  # no password fragment
    assert USER not in out


# ---- cookies, tokens, headers, urls, login bodies -----------------------------------

@pytest.mark.parametrize('text', [
    'Cookie: sessionid=%(t)s; other=1',
    'Set-Cookie: sessionid=%(t)s; Path=/; HttpOnly',
    "headers={'Cookie': 'sessionid=%(t)s', 'Authorization': 'Bearer %(t)s'}",
    'Authorization: Basic %(t)s',
    'Authorization: Bearer %(t)s',
    'sent Bearer %(t)s to server',
    '{"sessionid": "%(t)s", "result": 0}',
    'session_id=%(t)s',
    'GET http://admin:%(t)s@10.0.0.5/x',
    'https://10.0.0.5/api?access_token=%(t)s&x=1',
    "{'X-Session-Token': '%(t)s'}",
])
def test_cookies_tokens_and_headers(text):
    log, buf = make_logger()
    log.debug(text % {'t': TOKEN})
    assert TOKEN not in buf.getvalue()


def test_login_form_body_is_redacted():
    """The switch login posts RSA-encrypted etvapqp/rctater; ciphertext is replayable."""
    log, buf = make_logger()
    log.debug('POST body: etvapqp=AAAA%2Bbbbb%3D%3D&rctater=CCCC%2Fdddd%3D%3D')
    log.debug("POST data: {'etvapqp': 'AAAAbbbb==', 'rctater': 'CCCCdddd=='}")
    out = buf.getvalue()
    for frag in ('AAAA', 'CCCC'):
        assert frag not in out


# ---- exact secrets ----------------------------------------------------------------------

def test_registered_secret_is_removed_wherever_it_appears():
    assert logsafe.add_secret(PW)
    log, buf = make_logger()
    from urllib.parse import quote, quote_plus
    log.info('login failed for %s', PW)                       # raw, no key name at all
    log.info('url: http://h/x?p=%s', quote(PW, safe=''))      # percent-encoded
    log.info('form: %s', quote_plus(PW))
    log.info('json: %s', json.dumps(PW))
    log.info('repr: %r', PW)
    out = buf.getvalue()
    assert PW not in out
    assert quote(PW, safe='') not in out and quote_plus(PW) not in out
    assert json.dumps(PW)[1:-1] not in out and repr(PW)[1:-1] not in out


def test_short_secret_is_not_registered_so_it_cannot_shred_logs():
    assert logsafe.add_secret('ab') is False
    assert logsafe.add_secret(None) is False
    assert logsafe.redact('ab cab abc') == 'ab cab abc'


# ---- exceptions and tracebacks ----------------------------------------------------------

def test_exception_text_is_redacted():
    logsafe.add_secret(PW)
    log, buf = make_logger()
    try:
        raise RuntimeError('boom while using password=%s and token=%s' % (PW, TOKEN))
    except RuntimeError:
        log.exception('operation failed')
    out = buf.getvalue()
    assert 'operation failed' in out and 'RuntimeError' in out and 'Traceback' in out
    assert PW not in out and TOKEN not in out


def test_exception_passed_as_argument_is_redacted():
    log, buf = make_logger()
    log.error('cannot read switch: %s', RuntimeError('bad cookie: sessionid=%s' % TOKEN))
    assert TOKEN not in buf.getvalue()


# ---- diagnostics survive ------------------------------------------------------------------

@pytest.mark.parametrize('text', [
    'Araknis: logged in to 10.0.0.5',
    'Araknis: GET poe_port -> HTTP 200',
    'Araknis: POST poe_port_setting -> HTTP 500',
    'Araknis: login result=1',
    'Araknis: session expired on port_cfg (attempt 1 of 2), logging in again',
    'Araknis port 4: PoE Power Cycle',
    'Araknis port 23: PoE Off',
    'Araknis port 4: PoE is Off, power cycle ignored',
    'Araknis poll failed: HTTPConnectionPool(host=\'10.0.0.5\', port=80): Max retries exceeded',
    'Araknis: cannot read switch: login suppressed for 212 more seconds after a rejected login',
    'Araknis: switch rejected the login (result 1 invalid account)',
    'Araknis: 24 port nodes ready',
])
def test_useful_diagnostics_are_untouched(text):
    log, buf = make_logger()
    log.debug(text)
    assert text in buf.getvalue()


# ---- the framework case: child logger, parent's handler --------------------------------------

def test_filter_on_handler_covers_records_from_child_loggers():
    """udi_interface.interface is a child of 'udi_interface' and propagates to its handler.
    A filter attached to a *logger* never sees child-logger records; one on the handler does."""
    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    parent = logging.getLogger('araknis_fw')
    parent.handlers = [handler]
    parent.propagate = False
    parent.setLevel(logging.DEBUG)
    child = logging.getLogger('araknis_fw.interface')
    child.setLevel(logging.DEBUG)

    # filter on the parent LOGGER only: the child's record is NOT scrubbed
    only_logger = logsafe.RedactingFilter()
    parent.addFilter(only_logger)
    child.debug('cfg {"password": "hunter22"}')
    assert 'hunter22' in buf.getvalue()
    parent.removeFilter(only_logger)
    buf.truncate(0); buf.seek(0)

    logsafe.install()                                  # filter on the HANDLER
    assert logsafe._filter in handler.filters
    child.debug('cfg {"password": "hunter22"}')
    assert 'hunter22' not in buf.getvalue()


def test_install_is_idempotent_and_reaches_the_framework_handler():
    udi = pytest.importorskip('udi_interface')
    from udi_interface.polylogger import LOG_HANDLER
    logsafe.install()
    logsafe.install()
    assert LOG_HANDLER.handler.filters.count(logsafe._filter) == 1
    assert LOG_HANDLER.handler in logsafe.installed_on()


# ---- robustness -----------------------------------------------------------------------------

def test_redaction_failure_withholds_the_message(monkeypatch):
    log, buf = make_logger()

    def boom(_text):
        raise ValueError('regex exploded')

    monkeypatch.setattr(logsafe, 'redact', boom)
    log.info('password=hunter22')
    out = buf.getvalue()
    assert 'hunter22' not in out and 'withheld' in out


def test_unformattable_message_does_not_crash_or_leak():
    log, buf = make_logger()
    log.info('value %d', 'password=hunter22')           # TypeError inside getMessage()
    assert 'hunter22' not in buf.getvalue()


def test_non_string_message_objects_are_handled():
    log, buf = make_logger()
    log.info({'password': 'hunter22'})
    assert 'hunter22' not in buf.getvalue()


def test_large_messages_are_fast():
    big = ('0123456789abcdef' * 20000) + ' password=hunter22 ' + ('x ' * 50000)
    t0 = time.time()
    out = logsafe.redact(big)
    assert 'hunter22' not in out
    assert time.time() - t0 < 2.0


def test_multi_segment_cookie_header_is_redacted_whole():
    """Cookie names need not look secret; the whole header value must go."""
    log, buf = make_logger()
    log.debug('request headers -- Cookie: JSESS=%s; theme=%sB; lang=en' % (TOKEN, TOKEN))
    log.debug('response -- Set-Cookie: JSESS=%s; Path=/; HttpOnly' % TOKEN)
    out = buf.getvalue()
    assert TOKEN not in out and (TOKEN + 'B') not in out


# ---- print()/stderr output: udi_interface logs every write() call as its own record -----------

class _SplittingWriter:
    """Same shape as udi_interface's LoggerWriter: each write() becomes one log record,
    whitespace-only writes are dropped.  (funcName == 'write', like the real one.)"""

    def __init__(self, log_fn):
        self.log_fn = log_fn

    def write(self, message):
        if message.strip():
            self.log_fn(message.strip())

    def flush(self):
        pass


def test_print_splits_key_and_value_into_separate_records_and_both_are_handled():
    import contextlib
    log, buf = make_logger()
    with contextlib.redirect_stdout(_SplittingWriter(log.debug)):
        print('header:', 'X-Session-Token:', TOKEN)
        print('header:', 'Set-Cookie:', 'JSESS=%s; Path=/' % TOKEN)
        print('field', 'password', '=', 'hunter22')
        print('plain diagnostic line', 'port', 4)
    out = buf.getvalue()
    assert TOKEN not in out and 'hunter22' not in out
    assert 'plain diagnostic line' in out and 'port' in out      # a normal print is untouched
    # the raw material really was split, i.e. the value was a record of its own:
    assert out.count('\n') >= 10


def test_a_key_at_the_end_of_an_ordinary_log_line_does_not_swallow_the_next_line():
    log, buf = make_logger()
    log.info('request header names: Authorization:')       # not from write(): no carry-over
    log.info('Araknis port 4: PoE Power Cycle')
    assert 'Araknis port 4: PoE Power Cycle' in buf.getvalue()


def test_carry_over_applies_only_to_the_next_record_of_the_same_thread():
    import contextlib
    import threading
    log, buf = make_logger()
    with contextlib.redirect_stdout(_SplittingWriter(log.debug)):
        print('Cookie:', end='')                          # dangling key -> arms the carry-over
        t = threading.Thread(target=lambda: print('other thread line'))
        t.start(); t.join()                                # a different thread is unaffected
        print('value that follows the dangling key')       # swallowed
        print('next unrelated line')                       # kept
    out = buf.getvalue()
    assert 'other thread line' in out
    assert 'value that follows the dangling key' not in out
    assert 'next unrelated line' in out
