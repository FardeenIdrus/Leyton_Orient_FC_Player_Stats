"""The web "How playing styles work" page: the Streamlit page's own content
(`dashboard.style_reference`), per position."""
import pytest

from lofc.dashboard import style_reference as sr
from web_fakes import FakeStore, login, make


def _client():
    s = FakeStore()
    s.add(username="u", full_name="Ann Scout", role="scout", password="correct-horse-1")
    c, *_ = make(s)
    login(c, "u", "correct-horse-1")
    return c


def test_page_shell():
    r = _client().get("/playing-styles")
    assert r.status_code == 200 and "/js/playing_styles.js" in r.text and "Currently building" not in r.text


def test_api_needs_login():
    c, *_ = make(FakeStore())
    assert c.get("/api/playing-styles").status_code == 401


@pytest.fixture
def no_example(monkeypatch):
    from lofc.web.api import reference as api
    monkeypatch.setattr(api, "_example", lambda group: None)


def test_default_group_labels_and_table(no_example):
    from lofc.model import styles as st
    d = _client().get("/api/playing-styles").json()
    assert d["groups"] == list(st.STYLES) and d["group"] == "Winger"
    assert d["label_rules"] == sr.label_rules()
    t = sr.style_table("Winger")
    assert d["table"]["columns"] == ["Style", "Label", "Signals", "In plain words"]
    assert d["table"]["rows"] == t[["Style", "Label", "Signals", "In plain words"]].values.tolist()
    assert d["example"] is None


@pytest.mark.parametrize("group", ["Centre Back", "Full Back", "Centre Forward"])
def test_other_groups_drop_the_empty_label_column(no_example, group):
    d = _client().get(f"/api/playing-styles?group={group}").json()
    assert d["group"] == group and d["table"]["columns"] == ["Style", "Signals", "In plain words"]


def test_worked_example_on_the_real_database():
    """Real database (skipped without one): the example is the Streamlit page's own pick."""
    from sqlalchemy import create_engine
    from lofc.config import settings
    try:
        e = create_engine(settings.database_url)
        e.connect().close()
    except Exception:
        pytest.skip("no database")
    from lofc.dashboard.loaders import load_style_inputs
    from lofc.core.players_pool import default_season
    from lofc.web.api import reference as api
    ex = api._example("Winger")
    assert ex is not None and ex["style"] == "Wide" and 1 <= len(ex["rows"]) <= 2
    want = sr.worked_example(load_style_inputs(ex["season_id"]), "Winger")
    assert ex["rows"] == want["rows"] and ex["signals"] == want["signals"]
