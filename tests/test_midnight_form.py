from night_midnight_form import FormSnapshot, form


def test_form_snapshot_normalizes_scalar_and_repeated_values():
    snapshot = FormSnapshot({"user": "Ada", "lang": ["python", "rust"], "age": 13})

    assert snapshot["user"] == "Ada"
    assert snapshot.getone("lang") == "python"
    assert snapshot.getlist("lang") == ["python", "rust"]
    assert snapshot.getlist("user") == ["Ada"]
    assert snapshot["age"] == "13"


def test_form_from_event_is_safe_for_missing_or_invalid_payload():
    assert form(None).as_dict() == {}
    assert form({"type": "click"}).as_dict() == {}
    assert form({"form": "not-a-mapping"}).as_dict() == {}


def test_as_dict_returns_detached_lists():
    snapshot = form({"form": {"tag": ["night", "midnight"]}})
    copied = snapshot.as_dict()
    copied["tag"].append("browser")

    assert snapshot.getlist("tag") == ["night", "midnight"]
