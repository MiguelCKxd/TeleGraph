import unittest
from types import SimpleNamespace as NS
from unittest.mock import Mock
from telethon import types as t
from tg_ascii.backend import Message
from tg_ascii.expandable_text import project_quotes,toggle
from tg_ascii.message_tools import formatted_entities,entity_spans


class ExpandableTextTests(unittest.TestCase):
    def test_utf16_roundtrip_retains_collapsed_flag_and_nested_emoji(self):
        text='😀 '+'hello '*50
        spans=[(2,len(text),'collapsed_quote',''),(2,7,'bold','')]
        entities=formatted_entities(text,spans,[(0,1,42,'😀')])
        result,emoji=entity_spans(text,entities)
        self.assertCountEqual(result,spans);self.assertEqual(emoji,[(0,1,42,'😀')])
        self.assertTrue(next(e for e in entities if isinstance(e,t.MessageEntityBlockquote)).collapsed)

    def test_quote_projection_keeps_original_and_remaps_trailing_entities(self):
        text='😀\n'+('A'*300)+'\nAfter'
        entities=formatted_entities(text,[(2,302,'collapsed_quote',''),(303,308,'bold','')])
        message=Message(1,'A',text,'12:00',raw_text=text,entities=tuple(entities))
        original=tuple(bytes(e) for e in entities)
        visible,controls=project_quotes(message)
        self.assertEqual(controls,((2,False),));self.assertLess(len(visible.text),len(text))
        self.assertTrue(visible.text.endswith('…\nAfter'))
        spans,_=entity_spans(visible.raw_text,visible.entities)
        bold=next((a,b) for a,b,s,_ in spans if s=='bold')
        self.assertEqual(visible.raw_text[slice(*bold)],'After')
        self.assertEqual(tuple(bytes(e) for e in message.entities),original)
        expanded,controls=project_quotes(message,{2})
        self.assertIs(expanded,message);self.assertEqual(controls,((2,True),))

    def test_three_line_preview_and_quote_nesting_validation(self):
        text='one\ntwo\nthree\nfour\nfive'
        message=Message(1,'A',text,'12:00',raw_text=text,entities=(t.MessageEntityBlockquote(0,len(text),collapsed=True),))
        visible,_=project_quotes(message)
        self.assertEqual(visible.text,'one\ntwo\nthree…')
        with self.assertRaises(ValueError):formatted_entities(text,[(0,len(text),'quote',''),(0,3,'collapsed_quote','')])

    def test_toggle_is_scoped_and_bounded_without_network(self):
        app=NS(ui_account='A',active=2,render_messages=Mock())
        toggle(app,1,0,('B',2));self.assertFalse(hasattr(app,'_expanded_quotes'))
        toggle(app,1,0,('A',2));self.assertEqual(app._expanded_quotes[('A',2,1)],{0})
        toggle(app,1,0,('A',2));self.assertEqual(app._expanded_quotes[('A',2,1)],set())
        for ident in range(600):toggle(app,ident,0,('A',2))
        self.assertEqual(len(app._expanded_quotes),512)


if __name__=='__main__':unittest.main()
