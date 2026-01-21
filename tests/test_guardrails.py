from agent.config import GuardrailsConfig
from agent.guardrails.rules import Guardrails, parse_unified_diff


def test_allowlist_src_glob_matches_nested_files() -> None:
    cfg = GuardrailsConfig(
        allowed_paths=["src/**", "tests/**", "pyproject.toml"],
        blocked_paths=[".github/**", "**/.env*"],
        max_files_changed=10,
        max_diff_lines=500,
        max_attempts=3,
    )
    g = Guardrails(cfg=cfg)
    g.validate_paths(["src/demo_app/calculator.py"])


def test_parse_unified_diff_from_minimal_headers() -> None:
    diff = """--- a/src/demo_app/calculator.py
+++ b/src/demo_app/calculator.py
@@ -1,3 +1,3 @@
-x = 1
+x = 2
"""
    stats = parse_unified_diff(diff)
    assert stats.files == ["src/demo_app/calculator.py"]
    assert stats.changed_lines == 2


def test_guardrails_rejects_hunk_without_prefix_markers() -> None:
    cfg = GuardrailsConfig(
        allowed_paths=["src/**", "tests/**", "pyproject.toml"],
        blocked_paths=[".github/**", "**/.env*"],
        max_files_changed=10,
        max_diff_lines=500,
        max_attempts=3,
    )
    g = Guardrails(cfg=cfg)
    # Missing leading space markers in hunk lines -> would cause `git apply` corrupt patch.
    bad = """--- a/src/demo_app/calculator.py
+++ b/src/demo_app/calculator.py
@@ -1,1 +1,1 @@
def foo():
"""
    try:
        g.validate_diff(bad)
        raise AssertionError("expected GuardrailViolation")
    except Exception as e:  # noqa: BLE001
        assert "hunk line missing prefix" in str(e)

