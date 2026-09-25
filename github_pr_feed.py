import argparse
import json
import subprocess
import time
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from xml.etree import ElementTree as ET

import yaml


@dataclass(frozen=True)
class FeedConfig:
    name: str
    query: str


def load_feeds(path: Path) -> dict[str, FeedConfig]:
    raw_text = path.read_text()
    raw_feeds = yaml.safe_load(raw_text) if path.suffix in {".yaml", ".yml"} else json.loads(raw_text)
    if not isinstance(raw_feeds, dict):
        raise ValueError("Feed configuration must be an object")

    feeds = {}
    for name, definition in raw_feeds.items():
        query = definition.get("query") if isinstance(definition, dict) else None
        if not isinstance(name, str) or not isinstance(query, str) or not query.strip():
            raise ValueError(f"Feed {name!r} requires a nonempty query")
        feeds[name] = FeedConfig(name=name, query=query)
    return feeds


def atom_document(name: str, items: list[dict]) -> bytes:
    feed = ET.Element("feed", {"xmlns": "http://www.w3.org/2005/Atom"})
    ET.SubElement(feed, "title").text = name
    ET.SubElement(feed, "id").text = f"urn:github-pr-feed:{name}"
    ET.SubElement(feed, "updated").text = max(
        (item["updated_at"] for item in items),
        default="1970-01-01T00:00:00Z",
    )

    for item in items:
        entry = ET.SubElement(feed, "entry")
        ET.SubElement(entry, "title").text = item["title"]
        ET.SubElement(entry, "id").text = item["html_url"]
        ET.SubElement(entry, "link", {"href": item["html_url"]})
        ET.SubElement(entry, "updated").text = item["updated_at"]
        repository = item["repository_url"].removeprefix("https://api.github.com/repos/")
        ET.SubElement(entry, "summary").text = f"{repository} · {item['user']['login']}"

    return ET.tostring(feed, encoding="utf-8", xml_declaration=True)


class GitHubSearch:
    def run(self, query: str) -> list[dict]:
        result = subprocess.run(
            [
                "gh",
                "api",
                "-X",
                "GET",
                "search/issues",
                "-f",
                f"q={query}",
                "-f",
                "per_page=100",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        return json.loads(result.stdout)["items"]


class FeedCache:
    def __init__(self, search, ttl_seconds: int = 300, clock=time.monotonic):
        self.search = search
        self.ttl_seconds = ttl_seconds
        self.clock = clock
        self.entries: dict[str, tuple[float, bytes]] = {}

    def get(self, name: str, query: str) -> bytes:
        cached = self.entries.get(name)
        if cached and self.clock() - cached[0] < self.ttl_seconds:
            return cached[1]

        try:
            document = atom_document(name, self.search.run(query))
        except subprocess.CalledProcessError:
            if cached:
                return cached[1]
            raise

        self.entries[name] = (self.clock(), document)
        return document


def make_server(config_path: Path, search=None, port: int = 8787) -> HTTPServer:
    feeds = load_feeds(config_path)
    cache = FeedCache(search or GitHubSearch())

    class FeedHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            prefix = "/feeds/"
            if not self.path.startswith(prefix) or not self.path.endswith(".atom"):
                self.send_error(404, "Unknown feed")
                return

            name = self.path.removeprefix(prefix).removesuffix(".atom")
            feed = feeds.get(name)
            if feed is None:
                self.send_error(404, "Unknown feed")
                return

            try:
                document = cache.get(name, feed.query)
            except (subprocess.CalledProcessError, json.JSONDecodeError, KeyError):
                self.send_error(502, "GitHub search failed")
                return

            self.send_response(200)
            self.send_header("Content-Type", "application/atom+xml; charset=utf-8")
            self.send_header("Content-Length", str(len(document)))
            self.end_headers()
            self.wfile.write(document)

        def log_message(self, format, *args):
            return

    return HTTPServer(("127.0.0.1", port), FeedHandler)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=Path(__file__).with_name("feeds.yaml"))
    parser.add_argument("--port", type=int, default=8787)
    arguments = parser.parse_args()
    make_server(arguments.config, port=arguments.port).serve_forever()


if __name__ == "__main__":
    main()
