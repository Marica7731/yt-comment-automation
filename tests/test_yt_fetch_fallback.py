import urllib.error

from yt_comment_automation import yt_fetch


def _rate_limit_error():
    return urllib.error.HTTPError(
        "https://www.youtube.com/watch?v=abcdefghijk",
        429,
        "Too Many Requests",
        None,
        None,
    )


def test_innertube_429_is_not_switched_to_unverified_api(tmp_path, monkeypatch):
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
        raise AssertionError("429 must propagate without an API fallback")


def test_request_gap_is_configurable(monkeypatch):
    from yt_comment_automation import req_pace

    seen = []
    monkeypatch.setenv("YOUTUBE_REQUEST_MIN_GAP_SECONDS", "3")
    monkeypatch.setattr(req_pace, "pace", lambda gap: seen.append(gap))
    yt_fetch._throttle()
    assert seen == [3.0]
