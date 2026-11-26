"""The hosted part: what it does with the agent's stats."""
import pytest
from conftest import load

hosted = load('plugin')


class FakeStats:
    def __init__(self):
        self.merged = []

    def merge_agent(self, agent, payload):
        self.merged.append((agent, payload))


@pytest.mark.parametrize('dns', [None, 'junk', ['h'], {'hours': None}])
def test_an_odd_dns_part_keeps_the_cache_numbers(monkeypatch, dns):
    stats = FakeStats()
    monkeypatch.setattr(hosted, '_stats', lambda: stats)
    monkeypatch.setattr(hosted, '_dns', lambda: None)
    plugin = hosted.Plugin.__new__(hosted.Plugin)
    assert plugin.agent_stats({'id': 'a1'}, {'dns': dns, 'hours': []}) == {'ok': True}
    assert len(stats.merged) == 1


class SnapStats:
    """A cache one agent reported on: two Steam depots and an item of another cache."""
    def __init__(self):
        self.remote = {'a1': {'updated': 1000, 'downloads': [
            {'cache': 'steam', 'item': 'depot 228988', 'hit_bytes': 900, 'miss_bytes': 100, 'requests': 5,
             'clients': 12},
            {'cache': 'steam', 'item': 'depot 4242', 'hit_bytes': 300, 'miss_bytes': 0, 'requests': 2, 'clients': 6},
            {'cache': 'blizzard', 'item': 'tpr/wow', 'hit_bytes': 50, 'miss_bytes': 0, 'requests': 1, 'clients': 5}],
            'suspects': [{'cache': 'steam', 'item': 'depot 228988', 'files': 1, 'misses': 3}]}}

    def snapshot(self, hours=24, now=None):
        return {'configured': True, 'hit_bytes': 1250, 'miss_bytes': 100}


def test_known_depots_show_the_game_and_unknown_ones_their_id():
    names = hosted.depot_names([{'name': 'Example Game', 'depots': ['228988']}, {'name': 'No depots'}])
    page = hosted.overview(SnapStats(), now=1010, names=names)
    assert [(d['item'], d['name']) for d in page['downloads']] == [
        ('depot 228988', 'Example Game'), ('depot 4242', 'depot 4242'), ('tpr/wow', 'tpr/wow')]
    assert page['suspects'][0]['name'] == 'Example Game'


def test_the_downloads_widget_names_the_game(monkeypatch):
    monkeypatch.setattr(hosted, '_stats', lambda: SnapStats())
    monkeypatch.setattr(hosted, 'depot_names', lambda apps=None: {'228988': 'Example Game'})
    plugin = hosted.Plugin.__new__(hosted.Plugin)
    labels = [i['label'] for i in plugin.widget_downloads()['items']]
    assert labels == ['Example Game', 'depot 4242', 'tpr/wow']


def test_without_floorbit_applications_the_ids_stay(monkeypatch):
    import builtins
    real = builtins.__import__

    def no_applications(name, *args, **kwargs):
        if name == 'floorbit' and 'applications' in (args[2] or ()):
            raise ImportError(name)
        return real(name, *args, **kwargs)
    monkeypatch.setattr(builtins, '__import__', no_applications)
    assert hosted.depot_names() == {}
