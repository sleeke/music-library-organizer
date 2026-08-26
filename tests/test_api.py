"""API tests exercising the full workflow against a temp database."""

import os
import time

import pytest
from fastapi.testclient import TestClient

import app as app_module
from core import safety
from core.library_db import LibraryDB


@pytest.fixture()
def client(tmp_path, monkeypatch):
    db = LibraryDB(str(tmp_path / 'lib.db'))

    def fake_write_tags(path, fields):
        return True

    monkeypatch.setattr(app_module.safety, 'write_tags', fake_write_tags)
    application = app_module.create_app(str(tmp_path / 'lib.db'))
    application.state.db = db  # swap in the fixture handle
    with TestClient(application) as tc:
        yield tc, db
    db.close()


def _seed_file(db, path, **overrides):
    tags = {'artist': 'A', 'albumartist': 'A', 'album': 'L',
            'title': 'T', 'tracknumber': '1'}
    checksum = overrides.pop('checksum', 'c')
    tags.update(overrides)
    db.upsert_file({'path': path, 'filename': path.split('/')[-1], 'size': 1,
                    'mtime': 1.0, 'checksum': checksum,
                    'duration': 10.0, 'bitrate': 320000, **tags})


def test_library_listing(client):
    tc, db = client
    _seed_file(db, '/music/one.mp3')
    body = tc.get('/api/library').json()
    assert body['total'] == 1
    assert body['files'][0]['path'] == '/music/one.mp3'
    assert body['files'][0]['has_pending'] is False


def test_library_search_and_pagination(client):
    tc, db = client
    _seed_file(db, '/music/one.mp3', title='Yellow')
    _seed_file(db, '/music/two.mp3', title='Clocks')
    body = tc.get('/api/library', params={'q': 'clock'}).json()
    assert body['total'] == 1 and body['files'][0]['title'] == 'Clocks'
    body = tc.get('/api/library', params={'limit': 1}).json()
    assert body['total'] == 2 and len(body['files']) == 1


def test_scan_rejects_unknown_folder(client):
    tc, _ = client
    resp = tc.post('/api/scan', json={'folder': '/nonexistent-xyz'})
    assert resp.status_code == 400


def test_scan_job_completes(tmp_path, monkeypatch):
    folder = tmp_path / 'music'
    folder.mkdir()
    (folder / 'real.mp3').write_bytes(b'data')
    monkeypatch.setattr(app_module.scanner, 'read_tags', lambda p: {
        'artist': 'A', 'albumartist': 'A', 'album': 'L',
        'title': 'T', 'tracknumber': '1'})
    application = app_module.create_app(str(tmp_path / 'lib.db'))
    with TestClient(application) as tc:
        job_id = tc.post('/api/scan', json={'folder': str(folder)}).json()['job_id']
        # Give the background thread a head start, then poll with a generous
        # cap — CI runners can be slow to schedule the daemon thread.
        time.sleep(0.5)
        deadline = time.monotonic() + 30
        body = {'status': 'running'}
        while time.monotonic() < deadline:
            body = tc.get(f'/api/jobs/{job_id}').json()
            if body['status'] != 'running':
                break
            time.sleep(0.1)
        assert body['status'] == 'done'
        assert body['result']['scan']['total'] == 1
    assert tc.get('/api/jobs/nope').status_code == 404


def test_duplicates_endpoint_filters_dismissed(client):
    tc, db = client
    _seed_file(db, '/m/1.mp3', artist='X', title='Y')
    _seed_file(db, '/m/2.mp3', artist='x', title='y')
    clusters = tc.get('/api/duplicates').json()['clusters']
    assert len(clusters) == 1
    assert len(clusters[0]['members']) == 2
    tc.post('/api/duplicates/dismiss', json={'cluster_key': clusters[0]['key']})
    assert tc.get('/api/duplicates').json()['clusters'] == []


def test_trash_requires_indexed_paths(client, tmp_path):
    tc, db = client
    outside = tmp_path / 'outside.txt'
    outside.write_bytes(b'x')
    resp = tc.post('/api/trash', json={'paths': [str(outside)]})
    assert resp.status_code == 400
    assert outside.exists()


def test_trash_deletes_indexed_path(tmp_path, client, monkeypatch):
    tc, db = client
    victim = tmp_path / 'victim.mp3'
    victim.write_bytes(b'data')
    _seed_file(db, str(victim))
    def fake_send2trash(path):
        # Real send2trash removes the original; emulate that here.
        os.unlink(path)
        return '/Trash/victim.mp3'

    monkeypatch.setattr(app_module.safety, 'send2trash', fake_send2trash)
    resp = tc.post('/api/trash', json={'paths': [str(victim)]})
    assert resp.status_code == 200
    assert resp.json()['results'][0]['ok'] is True
    assert not victim.exists()
    assert db.get_file(str(victim)) is None


def test_audio_endpoint_requires_indexed_path(client, tmp_path):
    tc, db = client
    secret = tmp_path / 'secret.mp3'
    secret.write_bytes(b'data')
    assert tc.get('/api/audio', params={'path': str(secret)}).status_code == 400
    _seed_file(db, str(secret))
    assert tc.get('/api/audio', params={'path': str(secret)}).status_code == 200


def test_suggestion_review_flow(tmp_path, client):
    tc, db = client
    mp3 = tmp_path / 'song.mp3'
    mp3.write_bytes(b'data')
    _seed_file(db, str(mp3))  # complete tags => the real engine proposes nothing
    assert app_module.suggester.run_suggest_pass(db)['suggested'] == 0
    assert tc.get('/api/suggestions').json()['suggestions'] == []

    # Seed a pending suggestion directly to exercise the review endpoints.
    fid = db.get_file(str(mp3))['id']
    db.replace_suggestion(fid, {'title': 'Fixed'}, {'title': 'test'}, 0.88)
    cards = tc.get('/api/suggestions').json()['suggestions']
    assert len(cards) == 1
    card = cards[0]
    assert card['fields'] == {'title': 'Fixed'}
    # seeded with complete tags (title='T'), so `current` mirrors the DB row
    assert card['current']['title'] == 'T'
    assert card['path'] == str(mp3)

    tc.patch(f"/api/suggestions/{card['id']}", json={'fields': {'title': 'Edited'}})
    tc.post(f"/api/suggestions/{card['id']}/approve")
    summary = tc.post('/api/apply').json()
    assert len(summary['applied']) == 1 and summary['conflicts'] == []
    # Full valid tags ⇒ apply also renames into the organized <A>/<L>/NN - T layout
    expected = tmp_path / 'A' / 'L' / '01 - Edited.mp3'
    assert expected.exists()
    assert db.get_suggestion(card['id'])['status'] == 'applied'
    assert db.get_file(str(expected))['title'] == 'Edited'


def test_reject_flow(tmp_path, client):
    tc, db = client
    _seed_file(db, '/m/a.mp3')
    fid = db.get_file('/m/a.mp3')['id']
    db.replace_suggestion(fid, {'album': 'X'}, {}, None)
    sid = db.list_suggestions(status='pending')[0]['id']
    tc.post(f'/api/suggestions/{sid}/reject')
    assert db.get_suggestion(sid)['status'] == 'rejected'


def test_approve_batch(tmp_path, client):
    tc, db = client
    _seed_file(db, '/m/a.mp3')
    _seed_file(db, '/m/b.mp3')
    for p in ('/m/a.mp3', '/m/b.mp3'):
        db.replace_suggestion(db.get_file(p)['id'], {'album': 'Q'}, {}, None)
    ids = [s['id'] for s in db.list_suggestions(status='pending')]
    body = tc.post('/api/suggestions/approve-batch', json={'ids': ids}).json()
    assert body == {'approved': 2}
    assert len(db.list_suggestions(status='approved')) == 2


def test_patch_unknown_suggestion_404(client):
    tc, _ = client
    assert tc.patch('/api/suggestions/999', json={'fields': {}}).status_code == 404
