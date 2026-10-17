import unittest
from unittest.mock import patch,Mock
from simulator.fleet_care import FleetCareWorld,FleetCareRuntime
from simulator.common import uid


class FleetCareTests(unittest.TestCase):
    def test_orchestrator_activates_every_worker_with_exclusive_ownership(self):
        w=FleetCareWorld();w.status='running'
        for i in range(5):
            self.assertTrue(w.command(uid(),'orchestrator','assign',row=i,vehicle=f'W{i+1}')['accepted'])
            self.assertFalse(w.command(uid(),'orchestrator','assign',row=i,vehicle=f'W{i+1}')['accepted'])
        self.assertFalse(w.options());self.assertFalse(w.verify()['trees_complete'])
        self.assertTrue(w.verify()['all_workers_used'])
        self.assertFalse(w.command(uid(),'orchestrator','claim_complete')['accepted'])
        w.assignments['0']['status']='completed'
        self.assertEqual({o['arguments']['vehicle'] for o in w.options()},{'W1'})
        self.assertNotIn(0,{o['arguments']['row'] for o in w.options()})
        obs=w.observations()
        self.assertNotIn('weed',obs['tasks'][0]);self.assertNotIn('pest0',str(obs))

    def test_worker_sensor_routing_and_single_navigation_reservation(self):
        with patch('threading.Thread.start'):
            r=FleetCareRuntime(config=dict(mode='vision',engine='crusoe',arena='orchard'))
            a=r.make_child(0,'W1');b=r.make_child(1,'W2')
        try:
            r.children={'W1':a,'W2':b};a.world.begin();b.world.begin();r.coordinate_traffic()
            self.assertEqual(sum(c.navigation_gate.is_set() for c in r.children.values()),1)
            self.assertEqual(b.world.robot['id'],'W2')
            self.assertEqual(b.world.orchard['worker'],'W2')
            self.assertEqual(b.world.observations()['worker'],'W2')
            self.assertEqual(b.world.tasks,[r.world.tasks[1]])
            with self.assertRaisesRegex(ValueError,'sensor session'):r.sensor_worker(dict(worker='W2',mission_id=a.world.id))
            self.assertIs(r.sensor_worker(dict(worker='W2',mission_id=b.world.id)),b)
            a.world.robot['action']=None;r.coordinate_traffic();self.assertTrue(b.navigation_gate.is_set());self.assertFalse(a.navigation_gate.is_set())
        finally:r.close()

    def test_parent_start_storage_barrier_and_rejected_restore_preserve_children(self):
        with patch('threading.Thread.start'):
            r=FleetCareRuntime(config=dict(mode='vision',engine='crusoe',arena='orchard'))
        child=Mock();child.world.status='paused';r.children={'W1':child}
        try:
            def failed_start(*args):r.storage_error='failed commit'
            with patch('simulator.runtime.Runtime.start',side_effect=failed_start):r.start()
            child.start.assert_not_called()
            with patch('simulator.runtime.Runtime.restore',side_effect=ValueError('wrong arena')):
                with self.assertRaises(ValueError):r.restore('wrong')
            self.assertIs(r.children['W1'],child);child.close.assert_not_called()
        finally:r.close()

    def test_traffic_gate_checked_after_stow_transition(self):
        from simulator.arm import ik
        with patch('threading.Thread.start'):
            parent=FleetCareRuntime(config=dict(mode='vision',engine='crusoe',arena='orchard'))
            child=parent.make_child(0,'W1')
        try:
            w=child.world;w.status='running';w.phase='return';start=w.robot['position'][:]
            w.robot['action']=dict(kind='arm',start=w.joints[:],end=w.joints[:],duration=.05,elapsed=0)
            child.step(.5)
            self.assertEqual(w.robot['position'],start)
            self.assertEqual(w.robot['action']['kind'],'navigate')
        finally:child.close();parent.close()
