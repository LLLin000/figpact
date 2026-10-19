"""Untrusted model replies never grant new controls or persistence."""
import copy
import unittest

from figpact.edit_plan import check_plan, combine_contexts


class PlanBoundaryTest(unittest.TestCase):
    def test_rejects_unauthorized_stale_or_nonfinite_edits(self):
        context = {'route': 'overlay', 'scope': 'main', 'revision': 'r1',
                   'controls': [{'id': 'real-y-ticks'}]}
        good = {'status': 'READY', 'route': 'overlay', 'scope': 'main',
                'revision': 'r1', 'edits': [{'control_id': 'real-y-ticks', 'value': 8}],
                'preserve': ['science', 'view'], 'reason': 'Explicit y tick font size'}
        self.assertEqual(check_plan(good, context)['edits'][0]['value'], 8)
        changes = [
            {'revision': 'r0'}, {'scope': 'other'}, {'route': 'native'},
            {'commit': True}, {'preserve': ['science']},
            {'edits': [{'control_id': 'invented-errorbar', 'value': 8}]},
            {'edits': good['edits'] * 2}, {'status': 'REFUSE'},
        ] + [{'edits': [{'control_id': 'real-y-ticks', 'value': v}]}
             for v in (True, float('inf'), float('nan'), '8')]
        for change in changes:
            with self.subTest(change=change), self.assertRaises(ValueError):
                check_plan({**copy.deepcopy(good), **change}, context)

    def test_multi_route_plan_cannot_smuggle_another_routes_edit(self):
        context = combine_contexts([
            {'route': route, 'scope': 'main', 'revision': 'r1',
             'controls': [{'id': 'font'}]} for route in ('native', 'overlay')])
        plan = {'status': 'READY', 'route': 'native', 'scope': 'main',
                'revision': context['revision'],
                'edits': [{'control_id': 'overlay:font', 'value': 8}],
                'preserve': ['science', 'view'], 'reason': 'invalid mixed route'}
        with self.assertRaises(ValueError):
            check_plan(plan, context)
        plan['edits'][0]['control_id'] = 'native:font'
        self.assertEqual(check_plan(plan, context)['route'], 'native')


if __name__ == '__main__':
    unittest.main()
