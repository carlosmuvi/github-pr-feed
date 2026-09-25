import tempfile
import threading
import unittest
import plistlib
from subprocess import CalledProcessError
from types import SimpleNamespace
from unittest.mock import patch
from http.client import HTTPConnection
from pathlib import Path

from github_pr_feed import FeedCache, GitHubSearch, atom_document, load_feeds, make_server
from install_launch_agent import launch_agent_plist


ITEM = {
    "title": "PR one",
    "html_url": "https://github.com/o/r/pull/1",
    "updated_at": "2026-09-21T12:00:00Z",
    "repository_url": "https://api.github.com/repos/o/r",
    "user": {"login": "carlos"},
}


class FakeSearch:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.queries = []

    def run(self, query):
        self.queries.append(query)
        return next(self.responses)


class FailingSearch:
    def run(self, query):
        raise CalledProcessError(1, ["gh", "api"])


class FeedConfigurationTests(unittest.TestCase):
    def test_loads_named_yaml_github_query(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "feeds.yaml"
            path.write_text("foundation:\n  query: is:pr is:open\n")

            feeds = load_feeds(path)

        self.assertEqual(feeds["foundation"].query, "is:pr is:open")

    def test_loads_named_github_query(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "feeds.json"
            path.write_text('{"foundation": {"query": "is:pr is:open"}}')

            feeds = load_feeds(path)

        self.assertEqual(feeds["foundation"].query, "is:pr is:open")

    def test_rejects_feed_without_nonempty_query(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "feeds.json"
            path.write_text('{"foundation": {"query": ""}}')

            with self.assertRaisesRegex(ValueError, "foundation"):
                load_feeds(path)

    def test_atom_escapes_title_and_links_to_pull_request(self):
        document = atom_document(
            "foundation",
            [
                {
                    "title": "Use <safe>",
                    "html_url": "https://github.com/o/r/pull/1",
                    "updated_at": "2026-09-21T12:00:00Z",
                    "repository_url": "https://api.github.com/repos/o/r",
                    "user": {"login": "carlos"},
                }
            ],
        ).decode()

        self.assertIn("Use &lt;safe&gt;", document)
        self.assertIn('href="https://github.com/o/r/pull/1"', document)


class FeedServerTests(unittest.TestCase):
    def test_github_search_converts_gh_pr_result_to_atom_item(self):
        response = SimpleNamespace(
            stdout='{"items": [{"title":"PR one","html_url":"https://github.com/o/r/pull/1",'
            '"updated_at":"2026-09-21T12:00:00Z",'
            '"repository_url":"https://api.github.com/repos/o/r",'
            '"user":{"login":"carlos"}}]}'
        )
        with patch("github_pr_feed.subprocess.run", return_value=response):
            items = GitHubSearch().run("is:open team-review-requested:o/team")

        self.assertEqual(items, [ITEM])

    def test_cache_uses_successful_document_before_ttl(self):
        search = FakeSearch([[ITEM], [{**ITEM, "title": "PR two"}]])
        cache = FeedCache(search=search, ttl_seconds=300, clock=lambda: 100)

        first = cache.get("foundation", "is:pr")
        second = cache.get("foundation", "is:pr")

        self.assertEqual(first, second)
        self.assertEqual(search.queries, ["is:pr"])

    def test_expired_cache_survives_github_failure(self):
        now = [0]
        search = FakeSearch([[ITEM]])
        cache = FeedCache(search=search, ttl_seconds=300, clock=lambda: now[0])
        first = cache.get("foundation", "is:pr")
        now[0] = 301
        cache.search = FailingSearch()

        second = cache.get("foundation", "is:pr")

        self.assertEqual(first, second)

    def test_unknown_feed_returns_404(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "feeds.json"
            config_path.write_text('{"foundation": {"query": "is:pr"}}')
            server = make_server(config_path, search=FakeSearch([[ITEM]]), port=0)
            thread = threading.Thread(target=server.handle_request)
            thread.start()
            connection = HTTPConnection("127.0.0.1", server.server_port)
            connection.request("GET", "/feeds/missing.atom")
            response = connection.getresponse()
            response.read()
            thread.join()
            server.server_close()

        self.assertEqual(response.status, 404)

    def test_known_feed_returns_atom_document(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "feeds.json"
            config_path.write_text('{"foundation": {"query": "is:pr"}}')
            server = make_server(config_path, search=FakeSearch([[ITEM]]), port=0)
            thread = threading.Thread(target=server.handle_request)
            thread.start()
            connection = HTTPConnection("127.0.0.1", server.server_port)
            connection.request("GET", "/feeds/foundation.atom")
            response = connection.getresponse()
            document = response.read()
            thread.join()
            server.server_close()

        self.assertEqual(response.status, 200)
        self.assertEqual(response.getheader("Content-Type"), "application/atom+xml; charset=utf-8")
        self.assertIn(b"PR one", document)


class LaunchAgentTests(unittest.TestCase):
    def test_launch_agent_starts_server_with_config_and_restarts(self):
        payload = plistlib.loads(
            launch_agent_plist(
                Path("/Users/carlosmuvi/Code/github-pr-feed/.venv/bin/python"),
                Path("/Users/carlosmuvi/Code/github-pr-feed/github_pr_feed.py"),
                Path("/Users/carlosmuvi/Code/github-pr-feed/feeds.yaml"),
                Path("/Users/carlosmuvi/Library/Logs/github-pr-feed.log"),
            )
        )

        self.assertEqual(payload["Label"], "com.carlosmuvi.github-pr-feed")
        self.assertEqual(payload["ProgramArguments"][0], "/Users/carlosmuvi/Code/github-pr-feed/.venv/bin/python")
        self.assertEqual(payload["ProgramArguments"][1], "/Users/carlosmuvi/Code/github-pr-feed/github_pr_feed.py")
        self.assertIn("--config", payload["ProgramArguments"])
        self.assertTrue(payload["RunAtLoad"])
        self.assertTrue(payload["KeepAlive"])
        self.assertIn("/opt/homebrew/bin", payload["EnvironmentVariables"]["PATH"])


if __name__ == "__main__":
    unittest.main()
