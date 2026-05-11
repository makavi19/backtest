import sys
import pytest
sys.path.append('.')

from core.mt5_bridge import get_bridge

def test_bridge_dry_run():
    try:
        import MetaTrader5 as mt5
    except ImportError:
        mt5 = None

    if mt5 is None:
        return
    bridge = get_bridge()
    assert hasattr(bridge, 'get_historical_data')
    assert not bridge.connected
