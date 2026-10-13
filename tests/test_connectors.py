from omniclaw.connectors import compact, live_items


def test_compact_drops_noise_and_keeps_human_links():
    data = {
        "name": "a",
        "html_url": "https://github.com/x/a",
        "node_id": "n",
        "empty": None,
        "owner": {"login": "x", "avatar_url": "https://a/b.png"},
        "long": "z" * 600,
    }
    out = compact(data)
    assert out["html_url"] == "https://github.com/x/a"
    assert "node_id" not in out and "empty" not in out
    assert out["owner"] == {"login": "x"}
    assert len(out["long"]) == 501


def test_live_items_prefers_maintained_tools():
    items = [
        {"slug": "OLD", "description": "Deprecated: use the other one"},
        {"slug": "NEW", "description": "Lists things"},
    ]
    assert [i["slug"] for i in live_items(items)] == ["NEW"]
    assert live_items(items[:1]) == items[:1]
