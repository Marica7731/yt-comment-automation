import json
import urllib.error
from pathlib import Path

from yt_comment_automation import yt_fetch


def _rate_limit_error():
    return urllib.error.HTTPError(
        "https://www.youtube.com/watch?v=abcdefghijk",
        429,
        "Too Many Requests",
        None,
        None,
    )


def test_innertube_uses_official_api_fallback_when_key_exists(tmp_path, monkeypatch):
    expected = {"id": "abcdefghijk", "comments": [{"text": "0:01:00 Song"}]}
    monkeypatch.setenv("YOUTUBE_API_KEY", "test-key-not-real")
    monkeypatch.setattr(
        yt_fetch,
        "_fetch_youtube_innertube_raw",
        lambda *args, **kwargs: (_ for _ in ()).throw(_rate_limit_error()),
    )
    monkeypatch.setattr(
        yt_fetch,
        "_fetch_youtube_official_raw",
        lambda *args, **kwargs: expected,
    )

    assert yt_fetch.fetch_youtube_raw("abcdefghijk", cache_dir=tmp_path) == expected


def test_innertube_429_without_key_keeps_original_error(tmp_path, monkeypatch):
    monkeypatch.delenv("YOUTUBE_API_KEY", raising=False)
    original = _rate_limit_error()
    monkeypatch.setattr(
        yt_fetch,
        "_fetch_youtube_innertube_raw",
        lambda *args, **kwargs: (_ for _ in ()).throw(original),
    )

    try:
        yt_fetch.fetch_youtube_raw("abcdefghijk", cache_dir=tmp_path)
    except urllib.error.HTTPError as err:
        assert err is original
    else:
        raise AssertionError("429 should be re-raised when no API key is configured")


def test_official_api_fallback_failure_is_auditable(tmp_path, monkeypatch):
    monkeypatch.setenv("YOUTUBE_API_KEY", "test-key-not-real")
    monkeypatch.setattr(
        yt_fetch,
        "_fetch_youtube_innertube_raw",
        lambda *args, **kwargs: (_ for _ in ()).throw(_rate_limit_error()),
    )
    monkeypatch.setattr(
        yt_fetch,
        "_fetch_youtube_official_raw",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("quota exhausted")),
    )

    try:
        yt_fetch.fetch_youtube_raw("abcdefghijk", cache_dir=tmp_path)
    except yt_fetch.YtFetchError as err:
        assert "429" in str(err)
        assert "quota exhausted" in str(err)
    else:
        raise AssertionError("fallback failure should be wrapped for audit")


def test_official_api_parser_extracts_description_and_replies(tmp_path, monkeypatch):
    calls = []

    def fake_get(resource, params):
        calls.append((resource, params))
        if resource == "videos":
            return {"items": [{"snippet": {"description": "0:01:00 Song\nArtist"}}]}
        return {
            "items": [
                {
                    "snippet": {
                        "topLevelComment": {
                            "id": "top",
                            "snippet": {"textOriginal": "0:01:00 Song"},
                        }
                    },
                    "replies": {
                        "comments": [
                            {"id": "reply", "snippet": {"textOriginal": "reply text"}}
                        ]
                    },
                }
            ]
        }

    monkeypatch.setattr(yt_fetch, "_youtube_api_get", fake_get)
    raw = yt_fetch._fetch_youtube_official_raw(
        "abcdefghijk", Path(tmp_path), False, None, False
    )

    assert raw["description"].startswith("0:01:00 Song")
    assert [item["text"] for item in raw["comments"]] == ["0:01:00 Song", "reply text"]
    assert calls[0][0] == "videos"
    assert calls[1][0] == "commentThreads"
    assert (Path(tmp_path) / "fetch_times.json").is_file()
    assert json.loads((Path(tmp_path) / "yt_comment_ids.json").read_text())["abcdefghijk"] == [
        "top",
        "reply",
    ]
