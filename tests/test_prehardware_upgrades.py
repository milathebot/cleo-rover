from fastapi.testclient import TestClient

from rover.models import ExpressionCommand, ExpressionMode
from rover.renderer import render_expression
from rover.service import app

client = TestClient(app)


def test_config_includes_life_loop():
    data = client.get('/config').json()
    assert data['life_loop']['enabled'] is True
    assert data['life_loop']['behavior_cooldowns']['idle_presence_seconds'] == 45


def test_persistent_events_endpoint_roundtrip():
    r = client.post('/events', json={'kind': 'button', 'source': 'test', 'label': 'top button'})
    assert r.status_code == 200
    recent = client.get('/events/recent?limit=5').json()['events']
    assert any(e['label'] == 'top button' for e in recent)


def test_spatial_memory_roundtrip():
    payload = {
        'id': 'charger-dock',
        'label': 'Charging dock',
        'kind': 'dock',
        'zone': 'office',
        'bearing_deg': 15,
        'distance_m': 1.2,
        'confidence': 0.7,
        'notes': 'pre-hardware placeholder',
    }
    r = client.post('/map/remember', json=payload)
    assert r.status_code == 200
    assert r.json()['item']['observations'] >= 1
    items = client.get('/map').json()['items']
    assert any(item['id'] == 'charger-dock' for item in items)


def test_autonomy_dashboard_and_hub_bridge_exist():
    dash = client.get('/autonomy/dashboard')
    assert dash.status_code == 200
    assert 'Cleo Rover Autonomy' in dash.text
    hub = client.get('/cleo-hub')
    assert hub.status_code == 200
    assert 'hub' in hub.json()


def test_safety_simulator_runs_core_scenarios():
    r = client.post('/safety/simulate')
    assert r.status_code == 200
    results = r.json()['results']
    names = {row['scenario'] for row in results}
    assert 'front obstacle stops' in names
    assert all('passed' in row for row in results)


def test_all_expression_modes_render():
    for mode in ExpressionMode:
        frame = render_expression(ExpressionCommand(mode=mode, text=None, brightness=0.5), t=12.0)
        assert frame.image.size == (240, 320)
        assert frame.png_bytes().startswith(b'\x89PNG')
