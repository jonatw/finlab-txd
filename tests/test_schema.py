"""每個 data JSON 須通過 committed JSON Schema;openapi/catalog/feed 須為合法 JSON。
換 pipeline 輸出形狀時 schema 不同步 = 立刻紅燈。"""
import json
from pathlib import Path
from jsonschema import validate

ROOT = Path(__file__).resolve().parents[1]


def _v(data_name, schema_name):
    data = json.loads((ROOT / "site/data" / data_name).read_text())
    schema = json.loads((ROOT / "site/data/schema" / schema_name).read_text())
    validate(data, schema)


def test_signal_schema():
    _v("signal.json", "signal.schema.json")


def test_nav_schema():
    _v("nav.json", "nav.schema.json")


def test_metrics_schema():
    _v("metrics.json", "metrics.schema.json")


def test_health_schema():
    _v("health.json", "health.schema.json")


def test_manifests_and_feed_valid():
    json.loads((ROOT / "site/openapi.json").read_text())
    json.loads((ROOT / "site/.well-known/api-catalog").read_text())
    f = json.loads((ROOT / "site/feed.json").read_text())
    assert f["version"].endswith("1.1") and isinstance(f["items"], list) and f["items"], "feed 須有 items"
    it = f["items"][0]
    assert {"id", "title", "content_text", "date_published", "_txd"} <= set(it)
