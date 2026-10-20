"""Pipe tables in research prose."""
import unittest

from genealogy.markup import render


class TableTests(unittest.TestCase):
    def test_pipe_tables_render_escaped_with_references(self):
        resolve = lambda rid: ("people/ada.html", "Ada Fable") if rid == "ada" else None
        html = render("| Year | Who |\n|---|:---:|\n| 1801 | [[ada|Ada]] |\n| <b>1802</b> | [[secret-id|a cousin]] |\n| 1803 |", resolve)
        self.assertIn('<th scope="col">Year</th>', html)
        self.assertIn('<td><a href="people/ada.html">Ada</a></td>', html)
        self.assertIn("<td>&lt;b&gt;1802&lt;/b&gt;</td>", html)
        self.assertNotIn("secret-id", html)
        self.assertIn("<td>1803</td><td></td>", html)
        self.assertEqual("<p>| no rule | below |<br>text</p>", render("| no rule | below |\ntext", resolve))


if __name__ == "__main__":
    unittest.main()
