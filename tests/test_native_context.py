import unittest
from unittest.mock import patch, Mock
from native_ai_context import context_for

class ContextTests(unittest.TestCase):
    def row(self, ident, kind=1, direction='incoming'):
        return dict(id=ident, type=kind, direction=direction, createdAt='2026-01-01T00:00:0'+ident+'Z', body='哪个好', threadId='group')

    def test_text_followup_keeps_two_preceding_images(self):
        rows=[self.row('1',3),self.row('2',3),self.row('3')]
        preview=Mock();preview.fetch.side_effect=lambda ident:'image-'+ident
        with patch('native_ai_context.Previews',return_value=preview):
            result=context_for(rows,[rows[-1]],None,None,None)
        self.assertEqual([r['kind'] for r in result],['image','image','text'])
        self.assertEqual(preview.fetch.call_count,2)
        preview.close.assert_called_once()

    def test_historical_images_are_bounded_and_exclude_future_and_outgoing(self):
        rows=[self.row(str(i),3) for i in range(1,7)]+[self.row('7')]+[self.row('8',3),self.row('9',3,'outgoing')]
        preview=Mock();preview.fetch.return_value='image'
        with patch('native_ai_context.Previews',return_value=preview):
            result=context_for(rows,[rows[6]],None,None,None)
        self.assertEqual(preview.fetch.call_count,4)
        self.assertEqual([c.args[0] for c in preview.fetch.call_args_list],['3','4','5','6'])

    def test_image_failure_prevents_claiming_to_have_seen_it(self):
        rows=[self.row('1',3),self.row('2')]
        preview=Mock();preview.fetch.side_effect=ValueError('unavailable')
        with patch('native_ai_context.Previews',return_value=preview):
            with self.assertRaises(ValueError):context_for(rows,[rows[-1]],None,None,None)
        preview.close.assert_called_once()
