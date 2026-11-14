"""Parallel provider through the real registry and MCP HTTP transport.

Run: python tests/parallel_search_test.py
"""
import asyncio
import json
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx
from tubecli.core.workflow_engine import WorkflowEngine
from tubecli.nodes.registry import NodePolicy, create_node_from_dict


class ParallelSearchTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.requests = []
        self.payload = {"results": [{"title": "Asyncio", "url": "https://docs.python.org/3/library/asyncio.html", "excerpts": ["Python asynchronous I/O"]}]}
        self.tool_error = False
        self.text_only = False
        self.delay = False
        self.http_status = 200
        real_client = httpx.AsyncClient

        async def respond(request):
            self.requests.append(request)
            if request.method == "DELETE":
                return httpx.Response(200)
            body = json.loads(request.content)
            if "id" not in body:
                return httpx.Response(202)
            if body["method"] == "initialize":
                result = {"protocolVersion": body["params"]["protocolVersion"], "capabilities": {"tools": {}}, "serverInfo": {"name": "fixture", "version": "1"}}
            elif body["method"] == "tools/list":
                result = {"tools": [{"name": "web_search", "inputSchema": {"type": "object"}}]}
            else:
                self.assertEqual(body["method"], "tools/call")
                self.assertEqual(body["params"]["name"], "web_search")
                if self.delay:
                    await asyncio.sleep(60)
                if self.http_status != 200:
                    return httpx.Response(self.http_status, text="Service unavailable")
                result = {"isError": self.tool_error, "content": [{"type": "text", "text": "Search unavailable" if self.tool_error else json.dumps(self.payload)}]}
                if not self.text_only and not self.tool_error:
                    result["structuredContent"] = self.payload
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": result}, headers={"Mcp-Session-Id": "fixture-session"})

        self.client_patch = patch("httpx.AsyncClient", side_effect=lambda **kw: real_client(**dict(kw, transport=httpx.MockTransport(respond))))
        self.client_patch.start()
        self.addCleanup(self.client_patch.stop)

    def node(self, config=None):
        return create_node_from_dict({"id": "search", "type": "web_search", "config": config or {"provider": "parallel", "query": "Python asyncio documentation"}}, policy=NodePolicy.user("parallel-test"))

    async def test_workflow_transport_output_and_anonymous_headers(self):
        with patch.dict(os.environ, {"PARALLEL_API_KEY": "must-not-send", "TAVILY_API_KEY": "must-not-send"}):
            engine = WorkflowEngine([self.node()], [])
            result = await engine.run()
        self.assertFalse(result["has_errors"])
        output = engine.node_outputs["search"]
        self.assertEqual(set(output), {"results", "raw_html", "status"})
        self.assertIn("Python asynchronous I/O", output["results"])
        self.assertIn("https://docs.python.org/3/library/asyncio.html", output["results"])
        for request in self.requests:
            self.assertEqual(str(request.url), "https://search.parallel.ai/mcp")
            self.assertEqual(request.headers["User-Agent"], "TubeCLI/ParallelSearch (+https://github.com/tubecreate/tubecli)")
            self.assertNotIn("Authorization", request.headers)
            self.assertNotIn("x-api-key", request.headers)
        call = next(json.loads(r.content) for r in self.requests if r.content and b'tools/call' in r.content)
        self.assertEqual(call["params"]["arguments"]["search_queries"], ["Python asyncio documentation"])
        self.assertEqual(len(call["params"]["arguments"]["session_id"]), 32)
        self.assertNotIn("model_name", call["params"]["arguments"])

    async def test_text_response_and_stable_session(self):
        self.text_only = True
        node = self.node()
        for _ in range(2):
            self.assertIn("Asyncio", (await node.execute({}))["results"])
        ids = [json.loads(r.content)["params"]["arguments"]["session_id"] for r in self.requests if r.content and b'tools/call' in r.content]
        self.assertEqual(ids[0], ids[1])

    async def test_empty_results(self):
        self.payload = {"results": []}
        self.assertEqual((await self.node().execute({}))["status"], "⚠️ No results")

    async def test_tool_error_does_not_fall_back(self):
        self.tool_error = True
        node = self.node()
        with patch.object(node, "_fast_search", side_effect=AssertionError("wrong provider")):
            result = await node.execute({})
        self.assertIn("Parallel search failed: Search unavailable", result["status"])

    async def test_invalid_response_reports_error(self):
        self.payload = {"unexpected": []}
        self.assertIn("Invalid Parallel search response", (await self.node().execute({}))["status"])

    async def test_http_failure_marks_workflow_error(self):
        self.http_status = 503
        result = await WorkflowEngine([self.node()], []).run()
        self.assertTrue(result["has_errors"])

    async def test_cancellation_propagates(self):
        self.delay = True
        task = asyncio.create_task(self.node().execute({}))
        for _ in range(100):
            if any(b'tools/call' in r.content for r in self.requests):
                break
            await asyncio.sleep(.01)
        self.assertTrue(any(b'tools/call' in r.content for r in self.requests))
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task

    async def test_bounded_timeout(self):
        self.delay = True
        real_wait_for = asyncio.wait_for
        async def short_timeout(coro, timeout):
            self.assertEqual(timeout, 30)
            return await real_wait_for(coro, .05)
        with patch("tubecli.nodes.web_search_node.asyncio.wait_for", side_effect=short_timeout):
            result = await self.node().execute({})
        self.assertTrue(result["status"].startswith("❌"))

    async def test_default_and_saved_selections_keep_fallback_chain(self):
        for provider in [None, "default", "previous-selection"]:
            node = self.node({"query": "query", **({"provider": provider} if provider else {})})
            with patch.object(node, "_duckduckgo_search", return_value=[]), patch.object(node, "_google_search_fast", return_value=[]), patch.object(node, "_duckduckgo_lite", return_value=[{"title": "Existing", "link": "https://example.com", "snippet": "same"}]) as lite:
                self.assertIn("Existing", (await node.execute({}))["results"])
                lite.assert_called_once()
        self.assertEqual(self.requests, [])

    async def test_missing_extra_has_install_hint(self):
        import builtins
        original = builtins.__import__
        def missing(name, *args, **kwargs):
            if name == "mcp":
                raise ImportError("not installed")
            return original(name, *args, **kwargs)
        with patch("builtins.__import__", side_effect=missing):
            self.assertIn("tubecli[parallel-search]", (await self.node().execute({}))["status"])


if __name__ == "__main__":
    unittest.main()
