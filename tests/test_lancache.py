"""The LAN cache agent plugin: reading both logs hall-wide, the five-client rule, checks and
clearing. No network but localhost. (Floorbit's own tests cover the hosted side: the LAN cache view,
Games and DNS analytics.)"""
import http.server
import threading
import time

import pytest
from conftest import load
from floorbit.plugins.agent import MemoryContext, personal_data
from floorbit.plugins.base import PluginError

agent = load('agent')
logs = agent._logs
AgentPlugin = agent.AgentPlugin

NOW = 1794000000          # an hour boundary is not needed: everything is relative to it
STAMP = time.strftime('%d/%b/%Y:%H:%M:%S +0000', time.gmtime(NOW - 60))
QSTAMP = time.strftime('%d-%b-%Y %H:%M:%S', time.localtime(NOW - 60))
BLOCK = {"sends": {"stats": {"privacy": "aggregate"}, "status": {"privacy": "device"}}}


def access(cache, client, path, size, result, stamp=None):
    return (f'[{cache}] {client} / - - - [{stamp or STAMP}] "GET {path} HTTP/1.1" 200 {size} "-" '
            f'"Valve/Steam HTTP Client 1.0" "{result}" "lancache.steamcontent.com" "-"')


def query(client, name):
    return (f'{QSTAMP}.123 queries: info: client @0x7f3b2c0 {client}#53211 ({name}): '
            f'query: {name} IN A + (198.51.100.2)')


def hall_lines(stamp=None):
    out = []
    for i in range(6):        # six players fetch depot 228988
        out.append(access('steam', f'192.0.2.{10 + i}', f'/depot/228988/chunk/{i:040x}', 1000, 'HIT', stamp))
    for i in range(2):        # two fetch depot 999: too few to name it
        out.append(access('steam', f'192.0.2.{30 + i}', f'/depot/999/chunk/{i:040x}', 500, 'MISS', stamp))
    for _ in range(3):        # one file missed three times: the cache isn't keeping it
        out.append(access('blizzard', '192.0.2.40', '/tpr/wow/data/ab/cd/abcdef0123456789abcdef', 200, 'MISS', stamp))
    out.append('garbage line')
    return out


def test_items_name_what_was_fetched_not_who():
    assert logs.item_of('steam', '/depot/228988/chunk/abc') == 'depot 228988'
    assert logs.item_of('blizzard', '/tpr/wow/data/ab/cd/abcdef0123456789abcdef') == 'tpr/wow'
    assert logs.item_of('wsus', '/filestreamingservice/files/0123456789abcdef0123?P1=1') == 'filestreamingservice/files'
    assert logs.item_of('epicgames', '/') == '(root)'


def test_counter_is_hall_wide_and_names_only_with_five_clients():
    c = logs.Counter(min_clients=5)
    assert c.add_access(hall_lines(), now=NOW) == 11
    for i in range(5):
        c.add_queries([query(f'192.0.2.{10 + i}', 'cdn.steamcontent.com')], now=NOW)
    c.add_queries([query('192.0.2.99', 'secret-site.example.org'), query('192.0.2.99', 'pc-of-anna.lan')], now=NOW)
    p = c.payload(now=NOW)
    assert personal_data(p) is None
    hour = str(int((NOW - 60) // 3600 * 3600))
    assert p['hours'][hour]['steam'] == [6000, 1000, 8] and p['hours'][hour]['blizzard'] == [0, 600, 3]
    assert p['clients'][hour] == 9
    assert [d['item'] for d in p['downloads']] == ['depot 228988']
    assert p['downloads'][0]['clients'] == 6
    assert p['other_downloads'] == {'hit_bytes': 0, 'miss_bytes': 1600, 'requests': 5, 'items': 2}
    assert p['suspects'] == [{'cache': 'blizzard', 'item': 'tpr/wow', 'files': 1, 'misses': 3}]
    dns_hour = p['dns']['hours'][hour]
    assert dns_hour['lookups'] == 7 and list(dns_hour['sites']) == ['steamcontent.com']
    assert dns_hour['sites']['steamcontent.com'] == [5, 0, 5]
    assert p['dns']['services'] == {'steam': 5}
    assert c.payload(now=NOW)['hours'] == {}       # only hours that changed go again


def test_tail_reads_on_and_starts_over_after_rotation(tmp_path):
    log = tmp_path / 'access.log'
    log.write_text('one\ntwo\nhalf')
    t = logs.Tail(str(log))
    assert t.read() == ['one', 'two']
    with open(log, 'a') as f:
        f.write(' line\nthree\n')
    assert t.read() == ['half line', 'three']
    log.unlink()
    log.write_text('fresh\n')
    t2 = logs.Tail(str(log), t.state)
    assert t2.read() == ['fresh']
    assert logs.Tail(str(tmp_path / 'missing.log')).read() == []


class Heartbeat(http.server.BaseHTTPRequestHandler):
    answer = (204, 'cache-01')

    def do_GET(self):
        status, by = self.answer
        self.send_response(status)
        if by:
            self.send_header('X-LanCache-Processed-By', by)
        self.end_headers()

    def log_message(self, *args):
        pass


@pytest.fixture
def cache_server():
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Heartbeat)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f'127.0.0.1:{server.server_address[1]}'
    server.shutdown()


def make(tmp_path, **settings):
    ctx = MemoryContext('lancache', settings, BLOCK, state_dir=str(tmp_path))
    plugin = AgentPlugin(ctx)
    plugin.interval = 30
    plugin.counter = logs.Counter(settings.get('min_clients') or 5)
    plugin.positions = {}
    plugin.access = logs.Tail(settings['access_log']) if settings.get('access_log') else None
    plugin.queries = logs.Tail(settings['dns_log']) if settings.get('dns_log') else None
    plugin._clearing = None
    return ctx, plugin


def test_a_round_reads_checks_and_sends(tmp_path, cache_server):
    log = tmp_path / 'access.log'
    log.write_text('\n'.join(hall_lines()) + '\n')
    cache = tmp_path / 'cache'
    (cache / 'ab').mkdir(parents=True)
    ctx, plugin = make(tmp_path, access_log=str(log), cache_dir=str(cache), cache_host=cache_server)
    plugin.tick(now=NOW, everything=True)
    kinds = [k for k, _ in ctx.sent]
    assert kinds == ['stats', 'status']
    status = ctx.sent[1][1]
    assert status['heartbeat']['ok'] and status['heartbeat']['processed_by'] == 'cache-01'
    assert status['disk']['total'] > 0
    report = ctx.health_.report()
    assert report['status'] == 'ok' and report['metrics']['access_lines'] == 11
    assert (tmp_path / 'positions.json').exists()
    assert plugin.check().startswith('reading the access log, the cache answers')


def test_a_heartbeat_from_something_else_is_a_warning(tmp_path, cache_server):
    Heartbeat.answer = (200, None)
    try:
        ctx, plugin = make(tmp_path, cache_host=cache_server)
        plugin.tick(now=NOW)
        assert ctx.health_.report()['status'] == 'warning'
        assert 'not 204' in ctx.sent[-1][1]['heartbeat']['error']
        with pytest.raises(PluginError):
            plugin.check()
    finally:
        Heartbeat.answer = (204, 'cache-01')


def test_clearing_removes_only_nginx_hash_folders(tmp_path):
    cache = tmp_path / 'cache'
    for name in ('00', 'af'):
        (cache / name / '12').mkdir(parents=True)
        (cache / name / '12' / 'abcdef').write_text('x')
    (cache / 'notes').mkdir()
    (cache / 'zz').mkdir()
    _ctx, plugin = make(tmp_path, cache_dir=str(cache))
    assert 'Clearing' in plugin.action_clear_cache({})['message']
    deadline = time.time() + 5
    while plugin._clearing['running'] and time.time() < deadline:
        time.sleep(0.05)
    assert sorted(p.name for p in cache.iterdir()) == ['notes', 'zz']
    assert plugin._clearing['removed'] == 2
    _ctx, unset = make(tmp_path)
    with pytest.raises(PluginError, match='cache folder'):
        unset.action_clear_cache({})
