import unittest
from unittest.mock import patch
from station_city_resolution import resolver, read_directory
import function_availability as evidence

class ResolutionTests(unittest.TestCase):
    def test_official_exact_match_and_ambiguous_names_do_not_guess(self):
        lookup,issues=resolver({'stations':[{'name':'同名','city':'甲'},{'name':'同名','city':'乙'},{'name':'甲新站','city':'乙'}]}, {})
        self.assertEqual(lookup('甲新站'),'乙')
        self.assertEqual(lookup('同名'),'')
        self.assertEqual(lookup('甲不存在站'),'')
        self.assertEqual(len(issues),2)

    def test_manual_override_preserved_with_conflict_evidence(self):
        manual={'站':'人工城市'}
        lookup,issues=resolver({'stations':[{'name':'站','city':'后台城市'}]},manual)
        self.assertEqual(lookup('站'),'人工城市');self.assertIn('站',issues)
        self.assertEqual(manual,{'站':'人工城市'})

    def test_query_evidence_expires_and_cannot_cross_accounts(self):
        evidence.discard('xiaoxiang')
        with patch('function_availability.time.time',return_value=100): evidence.record('xiaoxiang','a','stations')
        with patch('function_availability.time.time',return_value=101):
            self.assertIn('stations',evidence.snapshot('xiaoxiang','a'));self.assertEqual(evidence.snapshot('xiaoxiang','b'),{})
        with patch('function_availability.time.time',return_value=401): self.assertEqual(evidence.snapshot('xiaoxiang','a'),{})
