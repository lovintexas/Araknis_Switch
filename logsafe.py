"""Credential redaction for this plugin's logs.

A logging.Filter that scrubs secrets from every record before the handler
formats and writes it.  It is attached to the *handlers* (not just our own
logger) because udi_interface logs through child loggers such as
'udi_interface.interface', whose records never pass through a filter on a
parent logger, and because the framework writes everything to one shared
file handler (logs/debug.log).

What it removes:
  * values of keys whose name contains password / passwd / pwd / secret /
    token / apikey / authorization / cookie / session id (JSON, Python
    dict repr, JSON nested inside a string, key=value and form bodies);
  * the values of 'username', 'user', 'pw', 'pass', 'sid' and 'session'
    keys (JSON / dict forms), so a dumped customParams never shows them;
  * Cookie / Set-Cookie / Authorization header lines, Bearer tokens and
    user:password@ in URLs;
  * the exact password (and its URL/JSON-escaped forms) once the plugin
    knows it -- see add_secret();
  * the same things inside exception text and stack info.

Limits (see README): this is pattern based.  Before the plugin has called
add_secret() a secret is recognised only by the *name* of the key it is
logged under, and the filter covers this process's handlers only -- not
PG3x's own logs or the MQTT traffic.
"""
import json
import logging
import re
import threading
import time
from urllib.parse import quote, quote_plus

REDACTED = '[REDACTED]'
MIN_SECRET_LEN = 4

_SECRET_WORDS = (
    'password', 'passwd', 'passphrase', 'pwd', 'secret', 'token', 'apikey',
    'api_key', 'authorization', 'cookie', 'session_id', 'session-id',
    'sessionid', 'etvapqp', 'rctater', 'pg3init',
)
_KEY = r'[\w.\-]*(?:%s)[\w.\-]*' % '|'.join(re.escape(w) for w in _SECRET_WORDS)
_IDENT = r'username|user_name|user|pw|pass|sid|session'

# key[:=]"value" in any quoting: "k": "v", 'k': 'v', k="v", and JSON nested in a
# string (\"k\": \"v\").  The closing quote must not be backslash-escaped.
_QUOTED = re.compile(
    r'''(?<![\w.\-])(?P<pre>(?P<bs>\\*)(?P<kq>["']?)(?:%s|%s)(?P=bs)(?P=kq)'''
    r'''\s*[:=]\s*(?P=bs)(?P<vq>["']))'''
    r'''.*?(?<!\\)(?P<close>(?P=bs)(?P=vq))''' % (_KEY, _IDENT),
    re.I)

# key=value / key: value with no quotes (form bodies, query strings, plain text).
_BARE = re.compile(
    r'''(?<![\w.\-])(?P<pre>(?P<kq>["']?)(?:%s|username)(?P=kq)\s*[:=]\s*)'''
    r'''(?![\s"'\\]|\[REDACTED)'''
    r'''(?:(?:bearer|basic|digest|token)\s+)?[^\s,;&}\])'"]+''' % _KEY,
    re.I)

# whole header lines whose value can contain spaces and semicolons
_HEADER = re.compile(
    r'''(?P<pre>(?<![\w.\-])(?:set-cookie|cookie|authorization|proxy-authorization)\s*:\s*)'''
    r'''(?!\[REDACTED)[^\r\n]+''', re.I)

_URL_USERINFO = re.compile(r'(?P<pre>\b[a-z][a-z0-9+.\-]*://)[^/\s:@]*:[^/\s@]*@', re.I)
_BEARER = re.compile(r'(?P<pre>\bbearer\s+)(?!\[REDACTED)[A-Za-z0-9._~+/=\-]{8,}', re.I)

# A record that ends with a secret-looking key and no value ("X-Session-Token:", "password").
_DANGLING_KEY = re.compile(r'''(?<![\w.\-])(?:%s|username)(?:\s*[:=]\s*["']?)?$''' % _KEY, re.I)
_DANGLING_WINDOW_S = 2.0
_SEPARATOR_ONLY = frozenset((':', '=', ':=', '=>', '->', '-', '"', "'"))

_lock = threading.Lock()
_secrets = set()
_ordered = ()


def add_secret(value):
    """Remember an exact secret (a password, a session token ...) so it is
    scrubbed wherever it shows up, whatever key it is logged under.  Values
    shorter than MIN_SECRET_LEN are ignored: they would shred ordinary text
    (they are still caught by key name)."""
    global _ordered
    if not isinstance(value, str) or len(value) < MIN_SECRET_LEN:
        return False
    variants = {value, quote(value, safe=''), quote_plus(value),
                json.dumps(value)[1:-1], repr(value)[1:-1]}
    variants = {v for v in variants if len(v) >= MIN_SECRET_LEN}
    with _lock:
        _secrets.update(variants)
        _ordered = tuple(sorted(_secrets, key=len, reverse=True))
    return True


def clear_secrets():
    global _ordered
    with _lock:
        _secrets.clear()
        _ordered = ()


def redact(text):
    """Return text with secrets replaced by [REDACTED]."""
    if not text or not isinstance(text, str):
        return text
    text = _QUOTED.sub(lambda m: m.group('pre') + REDACTED + m.group('close'), text)
    text = _HEADER.sub(lambda m: m.group('pre') + REDACTED, text)
    text = _BARE.sub(lambda m: m.group('pre') + REDACTED, text)
    text = _URL_USERINFO.sub(lambda m: m.group('pre') + REDACTED + '@', text)
    text = _BEARER.sub(lambda m: m.group('pre') + REDACTED, text)
    for secret in _ordered:
        if secret in text:
            text = text.replace(secret, REDACTED)
    return text


class RedactingFilter(logging.Filter):
    """Scrubs a record in place, then lets it through (never drops a record).

    Works whether the message arrived as a format string plus args
    (LOGGER.info('x %s', value)) or as an already-formatted string
    (LOGGER.debug('x {}'.format(value)), which is how udi_interface logs
    the PG3 config).  If redaction itself fails the message is withheld
    rather than written unredacted.

    print()/stderr output is the awkward case: udi_interface replaces sys.stdout
    and sys.stderr with a writer that logs every write() call as its own record,
    and print('header:', 'Cookie:', value) makes several write() calls -- so a key
    and its value arrive as separate records.  When such a record ends with a
    secret-looking key ("Cookie:", "password="), the next record from the same
    thread is withheld as well."""

    def __init__(self, name=''):
        super().__init__(name)
        self._tl = threading.local()

    def filter(self, record):
        try:
            if record.funcName == 'write' and getattr(self._tl, 'pending_until', 0) > time.monotonic():
                if record.getMessage().strip() in _SEPARATOR_ONLY:
                    return True              # just the "=" between key and value: stay armed
                self._tl.pending_until = 0
                record.msg = REDACTED
                record.args = ()
                return True
            self._scrub(record)
            if record.funcName == 'write' and _DANGLING_KEY.search(record.getMessage()):
                self._tl.pending_until = time.monotonic() + _DANGLING_WINDOW_S
        except Exception:
            record.msg = '[log message withheld: redaction error]'
            record.args = ()
            record.exc_info = None
            record.exc_text = None
            record.stack_info = None
        return True

    @staticmethod
    def _scrub(record):
        forced = False
        try:
            text = record.getMessage()
        except Exception:
            text = '%s %r' % (record.msg, record.args)
            forced = True
        new = redact(text)
        if forced or new != text:
            record.msg = new
            record.args = ()
        if record.exc_info and not record.exc_text and isinstance(record.exc_info, tuple):
            record.exc_text = logging.Formatter().formatException(record.exc_info)
        if record.exc_text:
            record.exc_text = redact(record.exc_text)
        if record.stack_info:
            record.stack_info = redact(record.stack_info)


_filter = RedactingFilter()


def _all_handlers():
    handlers = []
    loggers = [logging.getLogger()]
    loggers += [lg for lg in list(logging.root.manager.loggerDict.values())
                if isinstance(lg, logging.Logger)]
    for lg in loggers:
        handlers.extend(lg.handlers)
    try:  # the framework's shared file handler, even if not attached anywhere yet
        from udi_interface.polylogger import LOG_HANDLER
        handlers.append(LOG_HANDLER.handler)
    except Exception:
        pass
    return handlers


def install():
    """Attach the filter to every handler that exists now.  Idempotent and
    cheap: call it again after anything that may have added a handler."""
    for h in _all_handlers():
        if _filter not in h.filters:
            h.addFilter(_filter)
    return _filter


def installed_on():
    """Handlers that currently carry the filter (for tests/diagnostics)."""
    return [h for h in _all_handlers() if _filter in h.filters]
