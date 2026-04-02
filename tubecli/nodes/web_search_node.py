"""Built-in node: Web Search — lightweight search via HTTP.
No browser needed. Uses requests + HTML parsing to extract search results.
Optimized for speed: parallel requests, short timeouts, multiple fallbacks."""
from typing import Dict, Any, List
from tubecli.nodes.base_node import BaseNode, PortType
import requests
import re
import concurrent.futures
import time


class WebSearchNode(BaseNode):
    node_type = "web_search"
    display_name = "🔍 Web Search"
    description = "Fast web search via HTTP (no browser needed). Uses DuckDuckGo + Google fallback."
    icon = "🔍"
    category = "Network"

    def _setup_ports(self):
        self.add_input("query", PortType.TEXT, "Search query")
        self.add_output("results", PortType.TEXT, "Search results as formatted text")
        self.add_output("raw_html", PortType.TEXT, "Raw HTML snippet (for debugging)")
        self.add_output("status", PortType.TEXT, "Execution status")

    async def execute(self, inputs: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        query = inputs.get("query") or inputs.get("prompt") or inputs.get("text") or self.config.get("query", "")

        if not query:
            return {"results": "", "raw_html": "", "status": "Error: No search query provided"}

        print(f"  [WebSearch] Searching: {query}")
        start = time.time()

        try:
            results_text = self._fast_search(query)
            elapsed = time.time() - start
            if results_text:
                print(f"  [WebSearch] ✅ Got results in {elapsed:.1f}s")
                return {
                    "results": results_text,
                    "raw_html": "",
                    "status": f"✅ Found results for: {query} ({elapsed:.1f}s)",
                }
            else:
                return {
                    "results": f"No results found for: {query}",
                    "raw_html": "",
                    "status": "⚠️ No results",
                }
        except Exception as e:
            elapsed = time.time() - start
            print(f"  [WebSearch] ❌ Error after {elapsed:.1f}s: {e}")
            return {
                "results": f"Search error: {e}",
                "raw_html": "",
                "status": f"❌ Error: {e}",
            }

    def _fast_search(self, query: str, num_results: int = 6) -> str:
        """Fast search: try DuckDuckGo first (most reliable), then Google fallback.
        Uses short timeouts to avoid blocking."""
        
        # Strategy: DuckDuckGo HTML is the most reliable for programmatic access
        # Google often returns CAPTCHAs or blocks bot requests
        
        results = []
        
        # 1. Try DuckDuckGo first (fast, reliable, no CAPTCHA)
        try:
            results = self._duckduckgo_search(query)
        except Exception as e:
            print(f"  [WebSearch] DuckDuckGo failed: {e}")
        
        # 2. If DuckDuckGo failed, try Google
        if not results:
            try:
                results = self._google_search_fast(query)
            except Exception as e:
                print(f"  [WebSearch] Google failed: {e}")
        
        # 3. If both failed, try DuckDuckGo Lite (minimal HTML, ultra-fast)
        if not results:
            try:
                results = self._duckduckgo_lite(query)
            except Exception:
                pass

        if not results:
            return ""

        # Format results as readable text
        lines = [f"🔍 Kết quả tìm kiếm: \"{query}\"\n"]
        for i, r in enumerate(results[:num_results], 1):
            title = r.get("title", "No title")
            snippet = r.get("snippet", "")
            link = r.get("link", "")
            lines.append(f"{i}. {title}")
            if snippet:
                lines.append(f"   {snippet}")
            if link:
                lines.append(f"   🔗 {link}")
            lines.append("")

        return "\n".join(lines)

    def _duckduckgo_search(self, query: str) -> list:
        """DuckDuckGo HTML search — most reliable for bots."""
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7",
        }
        resp = requests.post(
            "https://html.duckduckgo.com/html/",
            data={"q": query, "b": ""},
            headers=headers,
            timeout=8,
        )
        resp.raise_for_status()

        results = []
        html = resp.text

        # DuckDuckGo HTML uses class="result__a" for titles
        title_pattern = re.compile(r'<a[^>]*class="result__a"[^>]*href="([^"]*)"[^>]*>(.*?)</a>', re.DOTALL)
        snippet_pattern = re.compile(r'<a[^>]*class="result__snippet"[^>]*>(.*?)</a>', re.DOTALL)

        titles_and_links = title_pattern.findall(html)
        snippets = snippet_pattern.findall(html)

        for i, (link, title_html) in enumerate(titles_and_links[:8]):
            title = re.sub(r'<[^>]+>', '', title_html).strip()
            snippet = ""
            if i < len(snippets):
                snippet = re.sub(r'<[^>]+>', '', snippets[i]).strip()
            
            # Clean DuckDuckGo redirect URL
            clean_link = link
            if "uddg=" in link:
                import urllib.parse
                parsed = urllib.parse.parse_qs(urllib.parse.urlparse(link).query)
                clean_link = parsed.get("uddg", [link])[0]

            if title:
                results.append({
                    "title": title,
                    "snippet": snippet,
                    "link": clean_link,
                })

        return results

    def _google_search_fast(self, query: str) -> list:
        """Google search with short timeout."""
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7",
        }

        url = "https://www.google.com/search"
        params = {"q": query, "num": 8, "hl": "vi"}

        resp = requests.get(url, params=params, headers=headers, timeout=8)
        resp.raise_for_status()

        html = resp.text
        results = self._parse_google_html(html)
        return results

    def _parse_google_html(self, html: str) -> list:
        """Parse Google search results from HTML."""
        results = []

        # Pattern: <a href="URL">...<h3>Title</h3>
        h3_pattern = re.compile(
            r'<a[^>]+href="(/url\?q=([^"&]+)[^"]*|https?://[^"]+)"[^>]*>.*?<h3[^>]*>(.*?)</h3>',
            re.DOTALL
        )

        for match in h3_pattern.finditer(html):
            raw_url = match.group(1)
            title = re.sub(r'<[^>]+>', '', match.group(3)).strip()

            link = raw_url
            if link.startswith("/url?q="):
                link = match.group(2)
            if "google.com" in link and "/search" in link:
                continue
            if not title:
                continue

            results.append({"title": title, "link": link, "snippet": ""})

        # Extract snippets
        snippet_pattern = re.compile(
            r'<span[^>]*class="[^"]*(?:st|IsZvec|VwiC3b|yXK7lf)[^"]*"[^>]*>(.*?)</span>',
            re.DOTALL
        )
        snippets = []
        for match in snippet_pattern.finditer(html):
            text = re.sub(r'<[^>]+>', '', match.group(1)).strip()
            if len(text) > 30:
                snippets.append(text)

        if len(snippets) < len(results):
            broad_pattern = re.compile(
                r'<div[^>]*class="[^"]*(?:VwiC3b|IsZvec|s3v9rd)[^"]*"[^>]*>(.*?)</div>',
                re.DOTALL
            )
            for match in broad_pattern.finditer(html):
                text = re.sub(r'<[^>]+>', '', match.group(1)).strip()
                if len(text) > 30:
                    snippets.append(text)

        for i, r in enumerate(results):
            if i < len(snippets):
                r["snippet"] = snippets[i]

        if not results:
            results = self._fallback_parse(html)

        return results

    def _fallback_parse(self, html: str) -> list:
        """Simpler fallback parsing for Google HTML."""
        results = []
        h3s = re.findall(r'<h3[^>]*>(.*?)</h3>', html, re.DOTALL)
        for h3 in h3s:
            title = re.sub(r'<[^>]+>', '', h3).strip()
            if title and len(title) > 5 and "Google" not in title:
                results.append({"title": title, "link": "", "snippet": ""})
        return results[:8]

    def _duckduckgo_lite(self, query: str) -> list:
        """DuckDuckGo Lite — ultra-minimal, fastest fallback."""
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            }
            resp = requests.get(
                "https://lite.duckduckgo.com/lite/",
                params={"q": query},
                headers=headers,
                timeout=6,
            )
            results = []
            # Lite version has simpler HTML - extract links and titles
            link_pattern = re.compile(
                r'<a[^>]*rel="nofollow"[^>]*href="([^"]+)"[^>]*class="result-link"[^>]*>(.*?)</a>',
                re.DOTALL
            )
            for match in link_pattern.finditer(resp.text):
                link = match.group(1)
                title = re.sub(r'<[^>]+>', '', match.group(2)).strip()
                if title and link:
                    results.append({"title": title, "link": link, "snippet": ""})

            # Also try simple td-based extraction (lite format)
            if not results:
                td_pattern = re.compile(
                    r'<td[^>]*>\s*\d+\.?\s*</td>\s*<td[^>]*>.*?<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
                    re.DOTALL
                )
                for match in td_pattern.finditer(resp.text):
                    link = match.group(1)
                    title = re.sub(r'<[^>]+>', '', match.group(2)).strip()
                    if title and "duckduckgo" not in link.lower():
                        results.append({"title": title, "link": link, "snippet": ""})

            return results[:8]
        except Exception:
            return []
