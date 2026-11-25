import tkinter as tk
import unittest

from tg_ascii.number_input import NumberField, parse, show, slider


class NumberInputTests(unittest.TestCase):
    def test_parse_accepts_commas_and_clamps(self):
        self.assertEqual(parse('2,5', 1, 8), 2.5)
        self.assertEqual(parse('99', 1, 8), 8)
        self.assertEqual(parse('12.6', 0, 48, integer=True), 13)
        self.assertIsNone(parse('abc', 0, 1))
        self.assertIsNone(parse('nan', 0, 1))
        self.assertEqual(show(1.5), '1.5')
        self.assertEqual(show(2.0), '2')

    def test_typed_number_beyond_slider_range_updates_variable(self):
        try:
            root = tk.Tk()
        except tk.TclError:
            self.skipTest('no display')
        root.withdraw()
        try:
            value = tk.DoubleVar(master=root, value=1)
            seen = []
            row = slider(root, value, 1, 3, seen.append, typed_high=8)
            row.field.text.set('6')
            row.field.apply()
            self.assertEqual(value.get(), 6)
            self.assertEqual(seen, [6])
            value.set(2.25)
            self.assertEqual(row.field.text.get(), '2.25')
            row.field.text.set('oops')
            row.field.apply()
            self.assertEqual(value.get(), 2.25)
            self.assertEqual(row.field.text.get(), '2.25')
        finally:
            root.destroy()


if __name__ == '__main__':
    unittest.main()
