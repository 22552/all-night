import pytest
from night_midnight import Midnight

def test_ws_connect_emits_reconnect_configuration():
    midnight = Midnight()
    midnight.ws_connect(
        'wss://example.test/ws',
        socket_id='chat',
        protocols=['json'],
        reconnect=True,
        reconnect_delay=0.25,
        reconnect_max_delay=4,
    )
    command = midnight.drain()[-1]
    assert command == {
        'op': 'ws_connect',
        'url': 'wss://example.test/ws',
        'socket_id': 'chat',
        'protocols': ['json'],
        'reconnect': True,
        'reconnect_delay_ms': 250,
        'reconnect_max_delay_ms': 4000,
    }

def test_ws_connect_can_disable_reconnect_and_validates_delays():
    midnight = Midnight()
    midnight.ws_connect('ws://example.test', reconnect=False)
    assert midnight.drain()[-1]['reconnect'] is False
    with pytest.raises(ValueError):
        midnight.ws_connect('ws://example.test', reconnect_delay=-1)
    with pytest.raises(ValueError):
        midnight.ws_connect('ws://example.test', reconnect_delay=2, reconnect_max_delay=1)
