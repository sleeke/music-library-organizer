"""Tests for Feature C: cover art fetch & embed (Discogs + ID3 APIC).

All network access is mocked. Contract under test:
- query_discogs_cover(artist, album) -> image URL string or None
  - uses a Discogs API token from env DISCOGS_TOKEN (skips when unset)
  - picks the highest-resolution result under ~1MB
- download_image(url, max_bytes) -> raw bytes or None
- embed_cover_art(mp3_path, image_data) -> bool
  - writes an APIC (front cover) frame via mutagen
- dry_run compatibility: fetch_cover_and_embed(..., dry_run=True) never writes
"""
import importlib.util
import os
import sys
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).resolve().parent.parent / "update-mp3-metadata.py"
spec = importlib.util.spec_from_file_location("update_mp3_module", str(MODULE_PATH))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class FakeResponse:
    def __init__(self, json_data=None, content=b"", status_code=200):
        self._json = json_data
        self.content = content
        self.status_code = status_code

    def json(self):
        if self._json is None:
            raise ValueError("no json")
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


SEARCH_PAYLOAD = {
    "results": [
        {
            "id": 1,
            "title": "Artist - Album",
            # small image -> should be skipped in favor of the bigger one
            "thumb": "https://img.discogs.com/thumb.jpg",
            "cover_image": {
                "resource_url": "https://img.discogs.com/small.jpg",
                "width": 300,
                "height": 300,
            },
        },
        {
            "id": 2,
            "title": "Artist - Album",
            "cover_image": {
                "resource_url": "https://img.discogs.com/big.jpg",
                "width": 600,
                "height": 600,
            },
        },
    ]
}


class TestQueryDiscogsCover:
    def test_returns_highest_res_url(self, monkeypatch):
        calls = {}

        def fake_get(url, params=None, headers=None, **kwargs):
            calls["url"] = url
            calls["params"] = params
            calls["headers"] = headers
            return FakeResponse(json_data=SEARCH_PAYLOAD)

        monkeypatch.setattr(module.requests, "get", fake_get)
        url = module.query_discogs_cover("Some Artist", "Some Album", token="tok")
        assert url == "https://img.discogs.com/big.jpg"
        assert "/database/search" in calls["url"]
        assert calls["params"]["type"] == "release"
        assert calls["params"]["artist"] == "Some Artist"
        assert calls["params"]["title"] == "Some Album"

    def test_sends_user_agent(self, monkeypatch):
        captured = {}

        def fake_get(url, **kwargs):
            captured.update(kwargs)
            return FakeResponse(json_data=SEARCH_PAYLOAD)

        monkeypatch.setattr(module.requests, "get", fake_get)
        module.query_discogs_cover("A", "B", token="tok")
        assert captured["headers"]["User-Agent"].startswith("mp3-metadata-poc")

    def test_no_results_returns_none(self, monkeypatch):
        monkeypatch.setattr(
            module.requests, "get",
            lambda *a, **k: FakeResponse(json_data={"results": []}))
        assert module.query_discogs_cover("Ghost", "Nothing") is None

    def test_http_error_returns_none(self, monkeypatch):
        monkeypatch.setattr(
            module.requests, "get",
            lambda *a, **k: FakeResponse(json_data={}, status_code=500))
        assert module.query_discogs_cover("A", "B") is None

    def test_connection_error_returns_none(self, monkeypatch):
        def boom(*a, **k):
            raise ConnectionError("no network")

        monkeypatch.setattr(module.requests, "get", boom)
        assert module.query_discogs_cover("A", "B") is None


class TestDownloadImage:
    def test_downloads_bytes(self, monkeypatch):
        payload = b"\x89PNG fake image data" * 10
        urls = []

        def fake_get(url, **kwargs):
            urls.append(url)
            return FakeResponse(content=payload)

        monkeypatch.setattr(module.requests, "get", fake_get)
        data = module.download_image("https://img.discogs.com/big.jpg")
        assert data == payload
        assert urls == ["https://img.discogs.com/big.jpg"]

    def test_enforces_size_cap(self, monkeypatch):
        big_payload = b"x" * (module.MAX_IMAGE_BYTES + 1)
        monkeypatch.setattr(
            module.requests, "get",
            lambda *a, **k: FakeResponse(content=big_payload))
        assert module.download_image("https://img.discogs.com/big.jpg") is None

    def test_error_returns_none(self, monkeypatch):
        def boom(*a, **k):
            raise ConnectionError("down")

        monkeypatch.setattr(module.requests, "get", boom)
        assert module.download_image("https://x/y.jpg") is None


@pytest.fixture
def mp3_with_tags(tmp_path):
    """Build a minimal valid MP3 with basic tags; returns its path."""
    from mutagen.id3 import ID3, TIT2
    from mutagen.mp3 import MP3

    path = tmp_path / "song.mp3"
    frame = bytes([0xFF, 0xFB, 0x90, 0x00]) + bytes(413)  # MPEG-1 Layer III
    with open(path, "wb") as f:
        f.write(frame * 10)

    tags = ID3()
    tags.add(TIT2(encoding=3, text="Test Song"))
    tags.save(str(path), v1=0, v2_version=3)
    return str(path)


FAKE_JPEG = b"\xff\xd8\xff\xe0" + b"jpegdata" * 100  # JPEG magic + filler


class TestEmbedCoverArt:
    def test_embeds_apic_frame(self, mp3_with_tags):
        ok = module.embed_cover_art(mp3_with_tags, FAKE_JPEG)
        assert ok is True

        from mutagen.id3 import ID3
        tags = ID3(mp3_with_tags)
        apic = tags.getall("APIC")
        assert len(apic) == 1
        assert apic[0].mime == "image/jpeg"
        assert apic[0].type == 3  # front cover
        assert bytes(apic[0].data) == FAKE_JPEG

    def test_replaces_existing_apic(self, mp3_with_tags):
        from mutagen.id3 import APIC, ID3
        # Pre-seed an old/low-res cover
        ID3(mp3_with_tags).add(APIC(encoding=3, mime="image/jpeg",
                                    type=3, desc="old", data=b"old"))
        ok = module.embed_cover_art(mp3_with_tags, FAKE_JPEG)
        assert ok is True
        tags = ID3(mp3_with_tags)
        apic_frames = tags.getall("APIC")
        assert len(apic_frames) == 1
        assert bytes(apic_frames[0].data) == FAKE_JPEG

    def test_preserves_existing_title(self, mp3_with_tags):
        module.embed_cover_art(mp3_with_tags, FAKE_JPEG)
        from mutagen.id3 import ID3
        tags = ID3(mp3_with_tags)
        assert str(tags.getall("TIT2")[0]) == "Test Song"

    def test_invalid_file_returns_false(self, tmp_path):
        bad = tmp_path / "bad.mp3"
        bad.write_bytes(b"not an mp3 at all")
        assert module.embed_cover_art(str(bad), FAKE_JPEG) is False


class TestFetchCoverAndEmbed:
    """Top-level orchestrator: respects dry_run and skip conditions."""

    @pytest.fixture
    def no_token(self, monkeypatch):
        monkeypatch.delenv("DISCOGS_TOKEN", raising=False)

    def test_dry_run_does_not_write(self, mp3_with_tags, monkeypatch, no_token):
        before = open(mp3_with_tags, "rb").read()
        ok = module.fetch_cover_and_embed(
            mp3_with_tags, artist="A", album="B", dry_run=True,
            discogs_token="tok")
        assert ok is None  # explicitly signals "nothing done"
        assert open(mp3_with_tags, "rb").read() == before

    def test_skips_when_no_album(self, mp3_with_tags, monkeypatch, no_token):
        called = []
        monkeypatch.setattr(module, "query_discogs_cover",
                            lambda *a, **k: called.append(1))
        result = module.fetch_cover_and_embed(
            mp3_with_tags, artist="A", album=None, dry_run=False,
            discogs_token="tok")
        assert result is None
        assert not called

    def test_full_pipeline_when_enabled(self, mp3_with_tags, monkeypatch, no_token):
        monkeypatch.setattr(module, "query_discogs_cover",
                            lambda artist, album, token=None:
                            "https://img.discogs.com/big.jpg")
        monkeypatch.setattr(module, "download_image",
                            lambda url, max_bytes=None: FAKE_JPEG)
        result = module.fetch_cover_and_embed(
            mp3_with_tags, artist="A", album="B", dry_run=False,
            discogs_token="tok", enabled=True)
        assert result is True
        from mutagen.id3 import ID3
        assert len(ID3(mp3_with_tags).getall("APIC")) == 1

    def test_disabled_by_default(self, mp3_with_tags, monkeypatch, no_token):
        called = []
        monkeypatch.setattr(module, "query_discogs_cover",
                            lambda *a, **k: called.append(1))
        # No --fetch-cover flag equivalent passed -> default off
        result = module.fetch_cover_and_embed(
            mp3_with_tags, artist="A", album="B", dry_run=False,
            discogs_token="tok", enabled=False)
        assert result is None
        assert not called
