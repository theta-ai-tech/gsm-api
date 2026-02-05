from functions.runtime_flags import triggers_enabled


def test_triggers_enabled_defaults_true(monkeypatch) -> None:
    monkeypatch.delenv("GSM_TRIGGERS_ENABLED", raising=False)
    assert triggers_enabled() is True


def test_triggers_enabled_false_values(monkeypatch) -> None:
    for value in ("0", "false", "False", "off", "no"):
        monkeypatch.setenv("GSM_TRIGGERS_ENABLED", value)
        assert triggers_enabled() is False


def test_triggers_enabled_true_values(monkeypatch) -> None:
    for value in ("1", "true", "True", "on", "yes"):
        monkeypatch.setenv("GSM_TRIGGERS_ENABLED", value)
        assert triggers_enabled() is True


def test_triggers_enabled_invalid_value_falls_back_to_true(monkeypatch) -> None:
    monkeypatch.setenv("GSM_TRIGGERS_ENABLED", "maybe")
    assert triggers_enabled() is True
