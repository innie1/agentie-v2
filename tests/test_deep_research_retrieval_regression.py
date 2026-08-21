import asyncio
import json
import unittest
from unittest.mock import AsyncMock, patch

from agentie.core import deep_research
from agentie.tools import web_tools


class DeepResearchRetrievalRegressionTests(unittest.TestCase):
    def test_search_web_retries_after_backend_failure_and_empty_result(self):
        expected=[{"title":"Church software","href":"https://example.com/church","body":"Useful result"}]
        with patch.object(web_tools,"_search_attempt",side_effect=[RuntimeError("auto down"),[],expected]) as attempt:
            # function_tool wrappers expose the original implementation through on_invoke_tool;
            # exercise the wrapper exactly as deep_research does.
            raw=asyncio.run(web_tools.search_web.on_invoke_tool(None,json.dumps({"query":"church management nigeria","max_results":5})))
        payload=json.loads(str(raw))
        self.assertEqual(len(payload["results"]),1)
        self.assertEqual(payload["results"][0]["url"],"https://example.com/church")
        self.assertEqual(payload["backend"],"brave")
        self.assertEqual(attempt.call_count,3)

    def test_collect_sources_preserves_search_error_diagnostics(self):
        error=json.dumps({"query":"church","results":[],"error":"Web search returned no usable results. auto: timeout"})
        with patch.object(deep_research,"_call_tool",new=AsyncMock(return_value=error)):
            queries,sources,errors=asyncio.run(deep_research.collect_sources("church management nigeria",breadth=2))
        self.assertGreaterEqual(len(queries),2)
        self.assertEqual(sources,[])
        self.assertTrue(errors)
        self.assertIn("timeout",errors[-1])

    def test_run_deep_research_returns_failure_detail_when_search_is_empty(self):
        async def fake_collect(*args,**kwargs):
            return ["q1"],[],["q1: Web search failed: connection refused"]
        with patch.object(deep_research,"collect_sources",new=fake_collect):
            result=asyncio.run(deep_research.run_deep_research("church apps",AsyncMock(),"agent:agt_alex:main"))
        self.assertEqual(result["sources"],[])
        self.assertIn("connection refused",result["report"])
        self.assertIn("connection refused",result["errors"][0])


if __name__=="__main__":
    unittest.main()
