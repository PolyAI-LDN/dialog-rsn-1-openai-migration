import asyncio
import importlib
import unittest
import sys
from types import SimpleNamespace as Event
sys.modules.setdefault('sounddevice', Event())
sys.modules.setdefault('openai', Event(AsyncOpenAI=object))
sys.modules.setdefault('dotenv', Event(load_dotenv=lambda *a,**kw:None))

class ParallelToolsTest(unittest.TestCase):
    def test_one_followup_after_all_tool_outputs_and_response_done(self):
        for name in ['before','after']:
            with self.subTest(client=name):
                module=importlib.import_module(name)
                sent=[]
                async def output(*,item):sent.append(('output',item['call_id']))
                async def create_response():sent.append(('response',None))
                events=[Event(type='response.output_item.done',item=Event(type='function_call',name='look_up_reservation',arguments='{}',call_id='a')),
                    Event(type='response.output_item.done',item=Event(type='function_call',name='look_up_reservation',arguments='{}',call_id='b')),
                    Event(type='response.done',response=Event(status='completed')),
                    Event(type='response.done',response=Event(status='completed'))]
                class Connection:
                    conversation=Event(item=Event(create=output))
                    response=Event(create=create_response)
                    def __aiter__(self):
                        async def generate():
                            for event in events:
                                yield event
                        return generate()
                args={'speaker':Event(clear=lambda:None)} if name=='before' else {}
                asyncio.run(module.handle_events(Connection(),one_turn=True,**args))
                self.assertEqual(sent,[('output','a'),('output','b'),('response',None)])

    def test_cancelled_or_failed_tool_response_does_not_restart_generation(self):
        for name in ['before','after']:
            for status in ['cancelled','failed']:
                with self.subTest(client=name,status=status):
                    module=importlib.import_module(name)
                    sent=[]
                    async def output(*,item):sent.append(('output',item['call_id']))
                    async def create_response():sent.append(('response',None))
                    events=[Event(type='response.output_item.done',item=Event(type='function_call',name='look_up_reservation',arguments='{}',call_id='a')),
                        Event(type='response.done',response=Event(status=status))]
                    class Connection:
                        conversation=Event(item=Event(create=output))
                        response=Event(create=create_response)
                        def __aiter__(self):
                            async def generate():
                                for event in events:yield event
                            return generate()
                    args={'speaker':Event(clear=lambda:None)} if name=='before' else {}
                    asyncio.run(module.handle_events(Connection(),one_turn=True,**args))
                    self.assertEqual(sent,[('output','a')])
