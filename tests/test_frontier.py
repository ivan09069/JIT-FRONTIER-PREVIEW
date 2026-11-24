import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from jit_frontier import Source, make_candidates, main, normalize_sources, render_html, from_crossref, from_github

class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        fixture = Path(__file__).resolve().parents[1] / 'demo_sources.json'
        raw = json.loads(fixture.read_text(encoding='utf-8'))
        self.a, self.b = raw['theme_a'], raw['theme_b']
        self.sources = [Source.from_dict(s) for s in raw['sources']]
        self.fixture = fixture

    def test_cross_type_evidence(self):
        candidates = make_candidates(self.sources, self.a, self.b, 5)
        self.assertGreater(len(candidates), 0)
        for candidate in candidates:
            self.assertEqual(len(candidate['evidence']), 2)
            left, right = candidate['evidence']
            self.assertNotEqual(left['theme'], right['theme'])
            self.assertNotEqual(left['kind'], right['kind'])
            self.assertIn('UNVERIFIED', candidate['status'])
            self.assertIn('falsifiable_test', candidate)

    def test_html_escapes_untrusted_metadata(self):
        report = {'theme_a': 'a<script>', 'theme_b': 'b', 'generated_utc':'today',
                  'sources':[], 'retrieval_errors':[], 'demo':True, 'candidates':[]}
        result = render_html(report)
        self.assertNotIn('a<script>', result)
        self.assertIn('a&lt;script&gt;', result)
        self.assertIn('JIT FRONTIER | Discovery Engine', result)
        self.assertIn('JIT://DISCOVERY', result)

    def test_deduplicate_urls(self):
        records = self.sources + [self.sources[0]]
        self.assertEqual(len(normalize_sources(records)), len(self.sources))

    def test_fixture_mode_creates_reports(self):
        with tempfile.TemporaryDirectory() as temp:
            rc = main(['--fixture',str(self.fixture),'--out',temp])
            self.assertEqual(rc, 0)
            data = json.loads((Path(temp)/'opportunities.json').read_text())
            self.assertTrue(data['demo'])
            self.assertEqual(data['name'], 'JIT FRONTIER')
            self.assertTrue(data['candidates'])
            self.assertTrue((Path(temp)/'index.html').is_file())

    def test_crossref_mapping(self):
        fake = {"message":{"items":[{"DOI":"10.1000/example", "title":["Example study"], "published":{"date-parts":[[2026,4,12]]}}]}}
        with patch('jit_frontier.read_json_url', return_value=fake):
            records = from_crossref('test', 1)
        self.assertEqual(records[0].url, 'https://doi.org/10.1000/example')
        self.assertEqual(records[0].year, 2026)
        self.assertEqual(records[0].kind, 'research')

    def test_github_mapping(self):
        fake = {"items":[{"html_url":"https://github.com/valid/example", "full_name":"valid/example", "description":"A tool"},
                         {"html_url":"http://not-github.invalid/bad", "full_name":"bad", "description":"No"}]}
        with patch('jit_frontier.read_json_url', return_value=fake):
            records = from_github('test', 2)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].kind, 'implementation')

    def test_no_live_results_does_not_generate_fake_report(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch('jit_frontier.from_crossref', side_effect=ValueError('API unreachable')):
                with patch('jit_frontier.from_github', side_effect=ValueError('API unreachable')):
                    rc = main(['--a','A','--b','B','--out',temp])
            self.assertEqual(rc, 2)
            self.assertFalse((Path(temp)/'index.html').exists())

    def test_no_false_novelty_claim(self):
        c = make_candidates(self.sources, self.a, self.b, 2)
        self.assertTrue(all('novelty' in i['confidence'] for i in c))
        self.assertTrue(all('prior_art_check' in i for i in c))

if __name__=='__main__':
    unittest.main()
