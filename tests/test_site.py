from html.parser import HTMLParser
import json
import re
from pathlib import Path
import tempfile
import unittest
from urllib.parse import unquote, urlsplit

from genealogy.case import ResearchCase
from genealogy.config import ProjectConfig
from genealogy.models import (AccessLevel as A, Citation, Claim, Confidence, Event, Evidence,
                              Finding, LivingStatus as L, Name, Person, Place, Relationship, Source)
from genealogy.site import build_site


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
        self.ids = set()
        self.duplicate_ids = set()

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if attrs.get('id'):
            if attrs['id'] in self.ids:
                self.duplicate_ids.add(attrs['id'])
            self.ids.add(attrs['id'])
        for key in ('href', 'src'):
            if attrs.get(key):
                self.links.append(attrs[key])


class SiteTests(unittest.TestCase):
    def case(self):
        case = ResearchCase('hidden-case-id', 'Hidden case title', 'Hidden case summary')
        for record in [
            Person('../traveller', names=[Name('Ada <Harbour>')], living=L.DECEASED,
                   notes='A fictional public biography </script>.', sensitivity=A.PUBLIC),
            Person('parent', names=[Name('Robin Harbour')], living=L.DECEASED, sensitivity=A.PUBLIC),
            Person('SECRET-ID', names=[Name('SECRET-NAME')], living=L.LIVING,
                   notes='SECRET-NOTES', sensitivity=A.PUBLIC),
            Place('port', 'Fictional port', latitude=50, longitude=-4),
            Event('birth', 'birth', date='1840', place_id='port', participant_ids=['../traveller']),
            Relationship('parentage', '../traveller', 'parent', 'parent', confidence=Confidence.POSSIBLE,
                         sensitivity=A.PUBLIC),
            Source('register', 'Fictional register <b>', repository='Town archive',
                   url='javascript:alert(1)', sensitivity=A.PUBLIC),
            Citation('folio', 'register', locator='page 7', quotation='Ada </script><img src=x onerror=alert(1)>',
                     sensitivity=A.PUBLIC),
            Claim('claim', '../traveller', 'birth', '1840', citation_ids=['folio'],
                  confidence=Confidence.DOCUMENTED, sensitivity=A.PUBLIC),
            Claim('second-claim', '../traveller', 'residence', 'Port', citation_ids=['folio'], sensitivity=A.PUBLIC),
            Evidence('assessment', 'claim', 'folio', 'Direct register entry', sensitivity=A.PUBLIC),
            Finding('finding', 'The birth is supported.', related_ids=['../traveller'],
                    evidence_ids=['assessment'], sensitivity=A.PUBLIC),
            Source('secret-source', 'SECRET-SOURCE', sensitivity=A.PRIVATE),
        ]:
            case.add(record)
        return case

    def test_site_is_public_safe_complete_and_linked(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = build_site(self.case(), ProjectConfig(name='Fictional <study>'), root)
            all_text = '\n'.join(p.read_text() for p in root.rglob('*') if p.is_file())
            for value in ('SECRET-ID', 'SECRET-NAME', 'SECRET-NOTES', 'SECRET-SOURCE',
                          'secret-source', 'hidden-case-id', 'Hidden case title', 'Hidden case summary'):
                self.assertNotIn(value, all_text)
            person = next(p for name, p in paths.items() if name.startswith('people/') and 'Ada &lt;Harbour&gt;' in p.read_text())
            dossier = person.read_text()
            for value in ('Fictional register &lt;b&gt;', 'page 7', 'Direct register entry',
                          'documented', 'possible', 'Town archive'):
                # Repository appears on the linked source page, other details in dossier.
                self.assertIn(value, dossier if value != 'Town archive' else paths['sources.html'].read_text())
            self.assertNotIn('href="javascript:', all_text)
            self.assertNotIn('<img src=x', dossier)
            shared = paths['data/site-data.js'].read_text()
            self.assertIn('\\u003c/script', shared)
            self.assertNotIn('</script', shared)
            self.assertIn('data/site-data.js', paths['sources.html'].read_text())
            self.assertIn('Fictional &lt;study&gt;', paths['index.html'].read_text())
            for name, path in paths.items():
                self.assertTrue(path.resolve().is_relative_to(root.resolve()))
                if path.suffix != '.html':
                    continue
                parsed = Links()
                parsed.feed(path.read_text())
                self.assertEqual(parsed.duplicate_ids, set(), name)
                for link in parsed.links:
                    url = urlsplit(link)
                    if url.scheme or url.netloc:
                        continue
                    target = (path.parent / unquote(url.path)).resolve() if url.path else path
                    self.assertTrue(target.is_file(), (name, link))
                    # A fragment of key=value pairs is an address the page's script reads (tree.html#view=branches&person=…).
                    if url.fragment and target.suffix == '.html' and not re.fullmatch(r'[\w-]+=[^&=]*(?:&[\w-]+=[^&=]*)*', url.fragment):
                        other = Links()
                        other.feed(target.read_text())
                        self.assertIn(url.fragment, other.ids, (name, link))
            data = json.loads(paths['data/site.json'].read_text())
            self.assertEqual(len(data['people']), 2)
            self.assertEqual(json.loads(paths['data/places.geojson'].read_text())['features'][0]['geometry']['coordinates'], [-4.0, 50.0])

    def test_empty_rebuild_removes_only_owned_stale_pages(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = build_site(self.case(), ProjectConfig(), root)
            stale = [p for name, p in first.items() if name.startswith('people/')]
            unrelated = root / 'people' / 'my-notes.html'
            unrelated.write_text('Owner content')
            empty = build_site(ResearchCase('empty', 'empty'), ProjectConfig(), root)
            self.assertTrue(all(not p.exists() for p in stale))
            self.assertEqual(unrelated.read_text(), 'Owner content')
            self.assertIn('No public people', empty['catalogue.html'].read_text())
            self.assertIn('No coordinates supplied', empty['places.html'].read_text())
            self.assertEqual(json.loads(empty['data/site.json'].read_text())['people'], [])

    def test_large_case_keeps_dossiers_local_and_output_linear(self):
        case = ResearchCase('large', 'Fictional scale fixture')
        for i in range(1000):
            case.add(Person(f'p-{i}', names=[Name(f'Fictional Person {i}')],
                            living=L.DECEASED, sensitivity=A.PUBLIC))
            case.add(Event(f'e-{i}', 'birth', date='1800', participant_ids=[f'p-{i}']))
        with tempfile.TemporaryDirectory() as tmp:
            paths = build_site(case, ProjectConfig(), Path(tmp))
            dossiers = [path for name, path in paths.items() if name.startswith('people/')]
            self.assertEqual(len(dossiers), 1000)
            self.assertLess(max(path.stat().st_size for path in dossiers), 10000)
            self.assertLess(sum(path.stat().st_size for path in paths.values()), 15000000)
            for path in dossiers[:2]:
                text = path.read_text()
                payload = text.split('<script type="application/json" id="site-data">', 1)[1].split('</script>', 1)[0]
                self.assertNotIn('people', json.loads(payload))

    def test_symlink_escape_rejected_before_any_writes(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as outside:
            root = Path(tmp)
            (root / 'data').symlink_to(Path(outside), target_is_directory=True)
            with self.assertRaisesRegex(ValueError, 'escapes'):
                build_site(self.case(), ProjectConfig(), root)
            self.assertEqual(list(Path(outside).iterdir()), [])
            self.assertFalse((root / 'index.html').exists())


if __name__ == '__main__':
    unittest.main()
