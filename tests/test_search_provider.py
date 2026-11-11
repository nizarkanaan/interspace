"""Real disposable provider processes; no network or account usage."""
import json
from pathlib import Path
import sys
import threading
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app/backend'))
sys.path.insert(0,str(Path(__file__).resolve().parent))
from provider import CodexProvider, ProviderError
import test_app


class SearchProviderTests(unittest.TestCase):
    setUp=test_app.ProviderTests.setUp
    executable=test_app.ProviderTests.executable

    def test_only_search_capability_accepts_and_records_search_events(self):
        binary=self.executable("print(json.dumps({'type':'item.completed','item':{'id':'search-1','type':'web_search','action':{'type':'open_page','url':'https://example.org/paper'}}}))\nprint(json.dumps({'type':'item.completed','item':{'type':'agent_message','text':'{\"summary\":\"ok\"}'}}))\nprint(json.dumps({'type':'turn.completed','usage':{'input_tokens':3}}))")
        provider=CodexProvider(binary,timeout=3)
        with self.assertRaisesRegex(ProviderError,'tool'):provider.run('test',{},self.root,threading.Event())
        events=[]
        result,usage=provider.search('public brief',{},self.root,threading.Event(),events.append)
        self.assertEqual(result,{'summary':'ok'})
        self.assertEqual(events[0]['urls'],['https://example.org/paper'])
        self.assertEqual(usage,{'input_tokens':3})

    def test_search_mode_is_live_and_ignores_user_integrations(self):
        binary=self.executable("args=' '.join(sys.argv)\nassert 'web_search=\"live\"' in args\nassert '--ignore-user-config' in args\nassert 'project_doc_max_bytes=0' in args\nassert '--ignore-rules' in args\nassert 'features.shell_tool=false' in args\nassert 'features.multi_agent=false' in args\nprint(json.dumps({'type':'item.completed','item':{'type':'agent_message','text':'{}'}}))\nprint(json.dumps({'type':'turn.completed'}))")
        self.assertEqual(CodexProvider(binary,timeout=3).search('brief',{},self.root,threading.Event(),lambda e:None)[0],{})

    def test_search_still_aborts_forbidden_tools(self):
        for kind in ('command_execution','file_change','mcp_tool_call','collab_tool_call','computer_use'):
            binary=self.executable("print(json.dumps({'type':'item.started','item':{'type':"+repr(kind)+"}}),flush=True)\ntime.sleep(2)")
            with self.subTest(kind=kind),self.assertRaisesRegex(ProviderError,'tool'):
                CodexProvider(binary,timeout=3).search('brief',{},self.root,threading.Event(),lambda e:None)

    def test_malformed_search_event_fails_closed(self):
        binary=self.executable("print(json.dumps({'type':'item.completed','item':{'type':'web_search','action':{'url':15}}}))\nprint(json.dumps({'type':'item.completed','item':{'type':'agent_message','text':'{}'}}))\nprint(json.dumps({'type':'turn.completed'}))")
        with self.assertRaisesRegex(ProviderError,'search|provenance'):
            CodexProvider(binary,timeout=3).search('brief',{},self.root,threading.Event(),lambda e:None)

    def test_known_usage_survives_invalid_final_response(self):
        binary=self.executable("print(json.dumps({'type':'item.completed','item':{'type':'agent_message','text':'bad json'}}))\nprint(json.dumps({'type':'turn.completed','usage':{'input_tokens':8,'output_tokens':2}}))")
        with self.assertRaises(ProviderError) as raised:
            CodexProvider(binary,timeout=3).run('brief',{},self.root,threading.Event())
        self.assertEqual(raised.exception.usage,{'input_tokens':8,'output_tokens':2})
