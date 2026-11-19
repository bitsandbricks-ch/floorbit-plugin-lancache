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
