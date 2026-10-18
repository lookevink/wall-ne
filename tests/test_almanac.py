import json
import unittest
from unittest.mock import patch
from simulator.almanac import Season,DayClock,PEST_SLOTS,SPROUT,MATURE,sun_times,sun_position,care_trees
from simulator.fleet_care import FleetCareWorld,FleetCareRuntime
from simulator.orchard_care import OrchardCare
from simulator.runtime import Runtime


def persisted(runtime):
    runtime.persisted=True;return True


class AlmanacTests(unittest.TestCase):
    def test_sun_path_matches_early_summer_central_valley(self):
        sunrise,sunset=sun_times(153)
        self.assertTrue(5.5*3600<sunrise<6.3*3600 and 20*3600<sunset<20.8*3600)
        noon,azimuth=sun_position(153,(sunrise+sunset)/2)
        self.assertGreater(noon,70);self.assertAlmostEqual(azimuth,180,delta=3)
        self.assertLess(sun_position(153,sunrise+3600)[1],90)  # morning sun stands in the east-northeast
        env=Season(7).next_day().environment(sunrise+3600)
        self.assertGreater(env['sun']['direction'][0],0)  # east is +x in the scene
        self.assertEqual(Season(7).environment(23*3600)['phase'],'night')

    def test_seasons_are_deterministic_and_round_trip_through_checkpoints(self):
        a=Season(11).next_day().next_day();b=Season(11).next_day().next_day()
        self.assertEqual(a.record(),b.record())
        restored=Season.from_record(json.loads(json.dumps(a.record())))
        self.assertEqual(restored.record(),a.record())
        self.assertNotEqual(Season(12).next_day().record()['trees'],a.record()['trees'])

    def test_overnight_ecology_applies_measured_care(self):
        today=Season(7).next_day();before=today.trees
        outcome={0:dict(moisture=65,fertilizer=before[0]['deficit'],weed_removed=True,pests_remaining=0,cared=True),
                 1:dict(moisture=before[1]['moisture'],weed_removed=False,pests_remaining=before[1]['pests'])}
        tomorrow=today.next_day(outcome);after=tomorrow.trees
        # Pulled weeds re-sprout as seedlings; missed weeds keep growing in place.
        self.assertEqual(after[0]['weed']['age'],0);self.assertEqual(after[0]['weed']['size'],SPROUT['size'])
        self.assertNotEqual(after[0]['weed']['specimen_seed'],before[0]['weed']['specimen_seed'])
        self.assertEqual(after[1]['weed']['specimen_seed'],before[1]['weed']['specimen_seed'])
        self.assertEqual(after[1]['weed']['age'],before[1]['weed']['age']+1)
        self.assertLessEqual(after[1]['weed']['size'],MATURE['size'])
        # Watered soil stays wetter overnight than untouched soil started.
        self.assertGreater(after[0]['moisture'],before[0]['moisture'])
        self.assertTrue(all(10<=t['moisture']<=58 and 0<=t['pests']<=len(PEST_SLOTS) for t in after))
        self.assertLessEqual(after[0]['deficit'],4+1e-9)
        log=tomorrow.history[-1]
        self.assertEqual((log['day'],log['cared'],log['weeds_pulled']),(1,1,1))
        self.assertGreaterEqual(log['pests_removed'],before[0]['pests'])
        self.assertEqual(tomorrow.previous['day'],1)

    def test_day_conditions_shape_care_tasks(self):
        season=Season(7).next_day();conditions=season.conditions()
        world=FleetCareWorld(7,10,conditions=conditions)
        for task,c in zip(world.tasks,conditions):
            self.assertEqual(task['tree'],c['tree']);self.assertEqual(len(task['pests']),c['pests'])
            self.assertEqual(task['prescription'],c['prescription']);self.assertEqual(task['moisture'],c['moisture'])
            self.assertEqual((task['weed']['size'],task['weed']['leaves']),(c['weed']['size'],c['weed']['leaves']))
        child=OrchardCare(7,1,'W3',world.tasks[2])
        self.assertEqual(child.moisture,conditions[2]['moisture'])
        self.assertEqual(child.tree_outcome(),dict(moisture=round(conditions[2]['moisture'],3),fertilizer=0,weed_removed=False,pests_remaining=conditions[2]['pests'],cared=False))
        # Default worlds remain unchanged by the season seam.
        self.assertEqual([t['tree'] for t in OrchardCare(7,10).tasks],care_trees())
        self.assertNotIn('moisture',OrchardCare(7,10).tasks[0]);self.assertEqual(OrchardCare(7,10).moisture,23.)

    def test_day_clock_runs_with_the_mission_and_sweeps_to_night(self):
        clock=DayClock(Season(7).next_day(),day_minutes=10);start=clock.clock
        self.assertLess(start,clock.sunrise)
        clock.tick(60,'running',0);self.assertAlmostEqual(clock.clock-start,(clock.sunset-clock.sunrise)/10,delta=1)
        held=clock.clock;clock.tick(60,'paused',1);self.assertEqual(clock.clock,held)
        for second in range(50):clock.tick(1,'completed',2+second)
        self.assertEqual(clock.mode,'night');self.assertGreaterEqual(clock.clock,clock.night)
        self.assertFalse(clock.due(60));clock.auto_advance=True;self.assertTrue(clock.due(60))
        dormant=DayClock(Season(7),auto_advance=True);dormant.tick(30,'running',0)
        self.assertEqual(dormant.mode,'night');self.assertFalse(dormant.due(100))


class EpochServerTests(unittest.TestCase):
    def test_full_care_always_uses_fast_control_even_with_stale_browser_settings(self):
        from simulator.background_storage import BackgroundRepository
        app=self.make_app()
        self.assertEqual(app.plan['care_controller'],'ultra_fast')
        self.assertEqual(app.plan['speed'],16)
        with patch.dict('os.environ',{'WALLNE_CARE_CONTROLLER':'standard'}):
            app.new_season(dict(mission='full_care',care_controller='standard',tree_count=169,speed=16))
        self.assertEqual(app.plan['care_controller'],'ultra_fast')
        self.assertEqual(app.fleet.config['care_controller'],'ultra_fast')
        self.assertIsInstance(app.fleet.repository,BackgroundRepository)
        child=app.fleet.make_child(0,'W1');self.addCleanup(child.close)
        self.assertEqual(child.config['care_controller'],'ultra_fast')
        self.assertIsInstance(child.repository,BackgroundRepository)

    def make_app(self):
        from simulator.server import App
        patches=[patch('threading.Thread.start'),patch.object(Runtime,'persist',persisted)]
        for p in patches:p.start();self.addCleanup(p.stop)
        app=App(recover_season=False);self.addCleanup(lambda:app.fleet.close())
        return app

    def test_next_day_starts_the_mission_and_carries_measured_care(self):
        app=self.make_app()
        app.next_day(dict(mission='full_care',mode='demo',speed=8))
        self.assertEqual(app.season.day,1);self.assertIsInstance(app.fleet,FleetCareRuntime)
        self.assertEqual(app.fleet.world.status,'running')  # agents are always on
        self.assertEqual(app.fleet.world.season['day'],1);self.assertEqual(app.fleet.config['season_day'],1)
        first=app.season.trees[0]
        app.fleet.world.assignments['0']=dict(vehicle='W1',status='completed',session_id='done')
        app.fleet.world.results['done']=dict(status='completed',completed_trees=[dict(moisture=65,fertilizer=first['deficit'])],inference=[])
        view=app.epoch_view();self.assertTrue(view['trees'][0]['cared']);self.assertEqual(view['trees'][0]['moisture'],65)
        previous=app.fleet
        app.next_day({})
        self.assertEqual(app.season.day,2);self.assertEqual(previous.world.status,'aborted')
        self.assertEqual(app.season.trees[0]['weed']['age'],0);self.assertEqual(app.season.history[-1]['cared'],1)
        self.assertEqual(app.fleet.world.season['previous']['outcomes']['0']['moisture'],65)

    def test_full_orchard_selection_survives_days_and_preserves_existing_trees(self):
        app=self.make_app()
        app.new_season(dict(seed=7,mission='full_care',tree_count=169,care_controller='ultra_fast',speed=16))
        self.assertEqual(len(app.fleet.world.tasks),169)
        self.assertEqual(len(app.season.conditions()),169)
        self.assertEqual(app.epoch_view()['plan']['tree_count'],169)
        self.assertEqual(len({(t['tree']['row'],t['tree']['column']) for t in app.fleet.world.tasks}),169)
        self.assertEqual([t['tree'] for t in app.fleet.world.tasks[:10]],care_trees(10))
        app.next_day({})
        self.assertEqual(len(app.fleet.world.tasks),169)
        app.next_day(dict(tree_count=10))
        self.assertEqual(len(app.fleet.world.tasks),10)
        self.assertEqual(len(app.season.trees),169)  # Unscheduled trees keep living.
        for invalid in (0,170,True,169.0):
            with self.assertRaises(ValueError):app.day_plan(dict(tree_count=invalid))
        season=Season(7).next_day().next_day()
        old=season.record()['trees']
        season.ensure_tree_count(169)
        self.assertEqual(season.trees[:10],old)
        self.assertEqual(season.trees[10:],Season(7,tree_count=169).next_day().next_day().trees[10:])
        self.assertEqual(Season.from_record(season.record()).trees,season.trees)

    def test_auto_advance_stops_after_two_blocked_days(self):
        app=self.make_app();app.new_season(dict(seed=3,mission='full_care'))
        self.assertEqual((app.season.seed,app.season.day),(3,1))
        app.pace(dict(auto_advance=True,day_minutes=5))
        app.fleet.world.status='blocked';app.next_day({},automatic=True);self.assertEqual(app.season.day,2)
        app.fleet.world.status='blocked';app.next_day({},automatic=True)
        self.assertEqual(app.season.day,2);self.assertFalse(app.clock.auto_advance);self.assertIn('blocked',app.season_notice)
        with self.assertRaises(ValueError):app.pace(dict(day_minutes=7))

    def test_restart_continues_the_latest_parent_season(self):
        app=self.make_app();season=Season(5).next_day().next_day()
        parent=dict(season=season.record(),mission_type='fleet_care',assignments={'1':dict(session_id='w')},results={'w':dict(completed_trees=[dict(moisture=65,fertilizer=3)])})
        rows=[dict(id='child',metadata=dict(configuration=dict(season_day=2,parent_session_id='p'))),dict(id='p',metadata=dict(configuration=dict(season_day=2)))]
        with patch.object(app.repository,'read',return_value=rows,create=True),patch.object(app.repository,'restore',side_effect=lambda sid:parent if sid=='p' else {},create=True):
            app.recover_season()
        self.assertEqual((app.season.seed,app.season.day,app.clock.mode),(5,2,'night'))
        app.next_day(dict(mission='full_care'))
        self.assertEqual(app.season.day,3);self.assertEqual(app.season.history[-1]['cared'],1)

    def test_saved_fleet_outcomes_survive_a_restart(self):
        from simulator.server import saved_outcomes
        state=dict(mission_type='fleet_care',assignments={'2':dict(session_id='s')},results={'s':dict(status='failed',completed_trees=[],outcome=dict(moisture=50,weed_removed=False,pests_remaining=1))})
        self.assertEqual(saved_outcomes(state),{2:dict(moisture=50,weed_removed=False,pests_remaining=1)})
        self.assertEqual(saved_outcomes(dict(arena='orchard',extracted=True)),{0:dict(weed_removed=True)})


if __name__=='__main__':unittest.main()
