import asyncio
import contextlib
import importlib
import io
import unittest
import sys
from types import SimpleNamespace as Event
sys.modules.setdefault('sounddevice', Event())
sys.modules.setdefault('openai', Event(AsyncOpenAI=object))
sys.modules.setdefault('dotenv', Event(load_dotenv=lambda *a,**kw:None))

class Connection:
    def __aiter__(self):
        async def events():
            for event in self.events:
                yield event
        return events()

class CancelledReplyTest(unittest.TestCase):
    def test_partial_cancelled_reply_is_not_prepended_to_next_reply(self):
        for name, kind in [('after', 'response.output_text'), ('before', 'response.output_audio_transcript')]:
            with self.subTest(client=name):
                module=importlib.import_module(name)
                conn=Connection()
                conn.events=[Event(type='response.created',response=Event(id='one')),
                    Event(type=kind+'.delta',delta='Unfinished old answer'),
                    Event(type='response.done',response=Event(status='cancelled')),
                    Event(type='response.created',response=Event(id='two')),
                    Event(type=kind+'.delta',delta='New answer'),
                    Event(type=kind+'.done',text='New answer')]
                out=io.StringIO()
                with contextlib.redirect_stdout(out):
                    args={'speaker':Event(clear=lambda:None)} if name=='before' else {}
                    asyncio.run(module.handle_events(conn,one_turn=False,**args))
                self.assertEqual(out.getvalue(),'Hotel:  New answer\n\n')
