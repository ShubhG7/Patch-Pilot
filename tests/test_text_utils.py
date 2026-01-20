from demo_app.text_utils import normalize_whitespace, slugify_title


def test_normalize_whitespace() -> None:
    assert normalize_whitespace("  hello   world \n") == "hello world"


def test_slugify_title() -> None:
    assert slugify_title("Fix:  Divide by Zero!!!") == "fix-divide-by-zero"


def test_slugify_title_empty() -> None:
    assert slugify_title("   ") == "issue"

