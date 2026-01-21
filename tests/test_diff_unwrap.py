from agent.graph import _extract_diff


def test_extract_diff_from_json_wrapper_with_escaped_newlines() -> None:
    text = '{"diff": "--- a/src/demo_app/calculator.py\\n+++ b/src/demo_app/calculator.py\\n@@ -1,1 +1,1 @@\\n-x\\n+y\\n"}'
    diff = _extract_diff(text)
    assert diff.startswith("--- a/src/demo_app/calculator.py")
    assert "+++ b/src/demo_app/calculator.py" in diff
    assert "@@" in diff

