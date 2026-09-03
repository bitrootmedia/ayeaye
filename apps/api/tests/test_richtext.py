"""services/richtext.py::from_markdown — pure functions, no database.

Every case also runs the result through sanitise(), because that is the
actual contract: from_markdown() never gets stored on its own, and a case
that looks right before sanitising but wrong after it would be the real bug.
"""

from app.services import richtext


def _stored(md: str) -> str | None:
    return richtext.sanitise(richtext.from_markdown(md))


def test_plain_text_becomes_a_paragraph():
    assert _stored("Just a sentence.") == "<p>Just a sentence.</p>"


def test_bold_italic_and_inline_code():
    out = _stored("**bold** and *italic* and `code`.")
    assert out == "<p><strong>bold</strong> and <em>italic</em> and <code>code</code>.</p>"


def test_h1_is_promoted_to_h2_not_dropped():
    # The editor's own toolbar never produces h1 — sanitise() would silently
    # unwrap it into plain text if from_markdown() didn't remap it first.
    assert _stored("# Title") == "<h2>Title</h2>"


def test_h2_and_h3_pass_through_unchanged():
    assert _stored("## Sub") == "<h2>Sub</h2>"
    assert _stored("### Sub sub") == "<h3>Sub sub</h3>"


def test_h4_through_h6_fold_down_to_h3():
    for marker in ("####", "#####", "######"):
        assert _stored(f"{marker} Deep") == "<h3>Deep</h3>"


def test_bullet_list():
    assert _stored("- one\n- two") == "<ul>\n<li>one</li>\n<li>two</li>\n</ul>"


def test_numbered_list():
    assert _stored("1. one\n2. two") == "<ol>\n<li>one</li>\n<li>two</li>\n</ol>"


def test_blockquote():
    assert _stored("> a quote") == "<blockquote>\n<p>a quote</p>\n</blockquote>"


def test_fenced_code_gets_the_language_class_the_highlighter_expects():
    out = _stored("```python\nprint(1)\n```")
    assert out == '<pre><code class="language-python">print(1)\n</code></pre>'


def test_link_survives_with_the_safety_attributes_sanitise_always_adds():
    out = _stored("[docs](https://example.com)")
    assert out == '<p><a href="https://example.com" rel="noopener noreferrer nofollow">docs</a></p>'


def test_an_image_reference_renders_as_nothing():
    # An image is an attachment, not a URL, and that rule does not bend for
    # markdown: there is no data-attachment-id to give it, so the orphan-img
    # strip in sanitise() removes it, exactly as it would a hand-typed
    # <img src="..."> in the HTML editor. Alone in the body, the emptied
    # paragraph collapses the whole result to None, same as an emptied
    # HTML editor does.
    assert _stored("![alt](https://example.com/x.png)") is None


def test_raw_html_inside_markdown_is_not_a_bypass():
    # from_markdown() does not sanitise on its own — the caller always runs
    # sanitise() afterward, and this is what proves that still happens: a
    # <script> smuggled inside markdown text must not survive the round trip.
    assert "<script" not in (_stored("<script>alert(1)</script>\n\nHello") or "")


def test_empty_input_is_a_no_op():
    assert richtext.from_markdown(None) == ""
    assert richtext.from_markdown("") == ""
    assert richtext.sanitise(richtext.from_markdown("")) is None
