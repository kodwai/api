from app.services.model_registry import normalize_model, display_for_slug


def test_known_anthropic_model():
    m = normalize_model("claude-opus-4-8")
    assert m == {"slug": "claude-opus-4-8", "display": "Opus 4.8", "provider": "anthropic"}


def test_alias_resolves_to_latest():
    assert normalize_model("opus")["slug"] == "claude-opus-4-8"


def test_cursor_thinking_variant():
    assert normalize_model("claude-4.5-sonnet-thinking")["display"] == "Sonnet 4.5"


def test_openai_model_with_provider():
    m = normalize_model("gpt-5.5", "openai")
    assert m["display"] == "GPT-5.5" and m["provider"] == "openai"


def test_default_and_empty_are_none():
    assert normalize_model("default") is None
    assert normalize_model("") is None
    assert normalize_model(None) is None


def test_unknown_model_is_slugified_but_visible():
    m = normalize_model("some-new-model-x", "openai")
    assert m == {"slug": "some-new-model-x", "display": "some-new-model-x", "provider": "openai"}


def test_display_for_slug_roundtrip():
    assert display_for_slug("claude-opus-4-8") == "Opus 4.8"
    assert display_for_slug("unknown-slug") == "unknown-slug"
    assert display_for_slug(None) is None
