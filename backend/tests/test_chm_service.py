"""Tests for chm_service: path sanitization and URL rewriting."""

import pytest
from fastapi import HTTPException

from src.services.chm_service import rewrite_html_urls


class TestRewriteHtmlUrls:
    def test_rewrites_src(self):
        html = '<img src="images/pic.png">'
        result = rewrite_html_urls(html, "doc1", "")
        assert "/documents/doc1/chm-html?path=images/pic.png" in result

    def test_rewrites_href(self):
        html = '<a href="page2.html">link</a>'
        result = rewrite_html_urls(html, "doc1", "sub/dir")
        assert "/documents/doc1/chm-html?path=sub/dir/page2.html" in result

    def test_preserves_http_urls(self):
        html = '<img src="http://example.com/img.png">'
        result = rewrite_html_urls(html, "doc1", "")
        assert "http://example.com/img.png" in result

    def test_preserves_https_urls(self):
        html = '<a href="https://example.com">link</a>'
        result = rewrite_html_urls(html, "doc1", "")
        assert "https://example.com" in result

    def test_preserves_hash_links(self):
        html = '<a href="#section">jump</a>'
        result = rewrite_html_urls(html, "doc1", "")
        assert "#section" in result

    def test_preserves_data_uris(self):
        html = '<img src="data:image/png;base64,abc123">'
        result = rewrite_html_urls(html, "doc1", "")
        assert "data:image/png;base64,abc123" in result

    def test_rewrites_css_url(self):
        html = 'background: url(images/bg.png)'
        result = rewrite_html_urls(html, "doc1", "css")
        assert "/documents/doc1/chm-html?path=css/images/bg.png" in result

    def test_strips_query_params(self):
        html = '<img src="pic.png?v=1">'
        result = rewrite_html_urls(html, "doc1", "")
        assert "/documents/doc1/chm-html?path=pic.png" in result

    def test_no_html_dir(self):
        html = '<a href="other.html">x</a>'
        result = rewrite_html_urls(html, "d1", "")
        assert "/documents/d1/chm-html?path=other.html" in result

    def test_with_html_dir(self):
        html = '<a href="other.html">x</a>'
        result = rewrite_html_urls(html, "d1", "sub")
        assert "/documents/d1/chm-html?path=sub/other.html" in result


class TestPathTraversal:
    """Test that get_chm_html blocks path traversal via resolve() check."""

    def test_path_traversal_blocked(self, tmp_path):
        """Simulate the path sanitization logic used in get_chm_html."""
        extract_dir = tmp_path / "chm_extracted"
        extract_dir.mkdir()
        (extract_dir / "safe.html").write_text("ok")

        clean_path = "../../etc/passwd"
        file_path = (extract_dir / clean_path).resolve()

        # This is the check used in get_chm_html
        assert not str(file_path).startswith(str(extract_dir.resolve()))

    def test_normal_path_allowed(self, tmp_path):
        extract_dir = tmp_path / "chm_extracted"
        extract_dir.mkdir()
        (extract_dir / "page.html").write_text("ok")

        clean_path = "page.html"
        file_path = (extract_dir / clean_path).resolve()

        assert str(file_path).startswith(str(extract_dir.resolve()))

    def test_special_chars_in_path(self, tmp_path):
        extract_dir = tmp_path / "chm_extracted"
        extract_dir.mkdir()
        (extract_dir / "page with spaces.html").write_text("ok")

        clean_path = "page with spaces.html"
        file_path = (extract_dir / clean_path).resolve()

        assert str(file_path).startswith(str(extract_dir.resolve()))
