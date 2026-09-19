"""Tests de web_search. Los de red se saltan solos si no hay internet."""
import unittest
from unittest.mock import patch

from tests.helpers import net_ok
from tools import find_agent_browser, web_search

NET = net_ok()


@unittest.skipUnless(NET, "sin conexion a internet")
class TestWebSearchQueries(unittest.TestCase):
    def test_topic_query_returns_abstract_and_wiki(self):
        r = web_search("dragon ball")
        self.assertIn("Dragon Ball", r)
        self.assertIn("wikipedia.org", r)
        self.assertIn("Summary from", r)

    def test_spanish_query_hits_es_wikipedia(self):
        r = web_search("quien es akira toriyama")
        self.assertIn("es.wikipedia.org", r)

    def test_junk_query_returns_no_results_error(self):
        r = web_search("xyzzyqqq12345blorp")
        self.assertIn("No web results found", r)

    @unittest.skipUnless(find_agent_browser(), "agent-browser no instalado")
    def test_url_query_distills_page(self):
        r = web_search("https://example.com")
        self.assertIn("Example Domain", r)


class TestWebSearchInputValidation(unittest.TestCase):
    def test_empty_query_is_error(self):
        r = web_search("")
        self.assertIn("ERROR", r)
        r = web_search("   ")
        self.assertIn("ERROR", r)


class TestWebSearchAutoFetch(unittest.TestCase):
    """Regla de decision de auto_fetch: solo se activa cuando DDG no da abstract."""

    @patch("tools._ddg_abstract", return_value=("summary text", "DuckDuckGo", "http://x", []))
    @patch("tools._wiki_search", return_value=[])
    @patch("tools._wiki_extract")
    def test_skips_fetch_when_abstract_present(self, mock_extract, _mock_wiki, _mock_ddg):
        web_search("query", auto_fetch=True, timeout=5, max_output_chars=3000, fetch_budget=2400)
        mock_extract.assert_not_called()

    @patch("tools._ddg_abstract", return_value=("", "", "", []))
    @patch("tools._wiki_search", return_value=[
        {"title": "Some Page", "snippet": "snip", "url": "http://es.wikipedia.org/wiki/Some_Page"}])
    @patch("tools._wiki_extract", return_value="extracto completo del articulo")
    def test_fetches_wiki_extract_when_no_abstract(self, mock_extract, _mock_wiki, _mock_ddg):
        r = web_search("query", auto_fetch=True, timeout=5, max_output_chars=3000, fetch_budget=2400)
        mock_extract.assert_called_once()
        self.assertIn("extracto completo del articulo", r)
        self.assertIn("Summary from es.wikipedia.org", r)


if __name__ == "__main__":
    unittest.main()
