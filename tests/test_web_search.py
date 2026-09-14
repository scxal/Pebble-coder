"""Tests de web_search. Los de red se saltan solos si no hay internet."""
import unittest

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


if __name__ == "__main__":
    unittest.main()
