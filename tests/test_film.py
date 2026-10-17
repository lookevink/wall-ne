import json
import unittest
from unittest.mock import patch
from simulator.almanac import Season
from simulator.film import Film,FilmDay,WORK_FRAMES,EVENING_FRAMES,NIGHT_FRAMES


def physical(state):
    return json.dumps([state['epoch']['label'],{k:v['position'] for k,v in state['vehicles'].items()},
                       {k:(w['observations']['tool_pose']['position'],w['opening'],w['phase']) for k,w in state['care_workers'].items()},
                       [w['removed'] for w in state['care_inventory']['weeds']],[p['removed'] for p in state['care_inventory']['pests']],
                       [t['moisture'] for t in state['epoch']['trees']]],sort_keys=True)


class FilmTests(unittest.TestCase):
    def test_scripted_fleet_completes_every_tree_through_checked_commands(self):
        day=FilmDay(Season(7).next_day())
        while not day.settled:day.step()
        self.assertEqual(sorted(day.done),list(range(10)))
        for world in day.done.values():
            self.assertEqual(world.status,'completed');self.assertTrue(all(world.verify().values()))
            self.assertTrue(any(e['type']=='extraction' for e in world.events))
        self.assertTrue(all(o['cared'] and o['weed_removed'] and o['pests_remaining']==0 for o in day.outcomes().values()))
        self.assertLess(day.time,600)

    def test_a_seed_always_renders_the_same_paced_frames(self):
        first=list(Film(7,1).frames());second=list(Film(7,1).frames())
        self.assertEqual(len(first),WORK_FRAMES+EVENING_FRAMES+NIGHT_FRAMES)
        self.assertEqual([physical(s) for s in first],[physical(s) for s in second])
        self.assertEqual(first[WORK_FRAMES-1]['epoch']['label'],'15:30');self.assertEqual(first[WORK_FRAMES-1]['cared'],10)
        self.assertEqual(first[-1]['epoch']['mode'],'night');self.assertEqual(first[-1]['epoch']['phase'],'night')
        self.assertEqual(first[0]['epoch']['phase'],'dawn');self.assertEqual(first[-1]['controller'],'scripted')

    def test_film_frames_resume_deterministically(self):
        from simulator.server import App
        with patch('threading.Thread.start'):
            app=App(recover_season=False)
            app.start_film(dict(seed=3,days=1))
            ahead=app.film_frames(dict(start=0,count=4))['frames'];again=app.film_frames(dict(start=2,count=1))['frames']
            self.assertEqual(physical(again[0]),physical(ahead[2]))
            with self.assertRaises(ValueError):app.film_frames(dict(reel='other',start=0))


if __name__=='__main__':unittest.main()
