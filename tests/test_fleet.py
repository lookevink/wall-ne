import unittest
from simulator.engine import Mission
from simulator.agents import DemoController
from simulator.common import uid

class FleetTests(unittest.TestCase):
    def run_mission(self,seed,faults=False):
        m=Mission(seed); m.status='running'; c=DemoController(); broken=False
        for i in range(6200):
            c.step(m); m.tick(.25)
            if faults and m.time>45 and not broken:
                m.breakdown('W1'); m.breakdown('W2'); broken=True
                m=Mission.restore(m.checkpoint())
            if m.status!='running': break
        self.assertEqual(m.status,'completed',(seed,m.time,m.verify()))
        self.assertTrue(all(m.verify().values()))
        return m

    def test_nominal_and_two_failures(self):
        for seed in [7,8,31]:
            with self.subTest(seed=seed):
                self.run_mission(seed); self.run_mission(seed,True)

    def test_false_claim_and_duplicate(self):
        m=Mission(); original=m.checkpoint()
        result=m.command('same','orchestrator','claim_complete')
        self.assertFalse(result['accepted'])
        self.assertEqual(result,m.command('same','orchestrator','activate_spare'))
        self.assertEqual(original['zones'],m.zones)
        m.command('a','orchestrator','assign',row=0,vehicle='W1')
        self.assertFalse(m.command('b','W1','inspect',zone='0:0',ownership_version=0)['accepted'])

    def test_partial_water_restore_and_impossible_deadline(self):
        m=Mission(); m.status='running'; c=DemoController()
        for i in range(2000):
            c.step(m); m.tick(.25)
            partial=next((z for z in m.zones.values() if 0<z['delivered']<10),None)
            if partial: break
        self.assertIsNotNone(partial)
        saved=m.checkpoint(); self.assertEqual(Mission.restore(saved).checkpoint(),saved)
        m.breakdown(next(v['id'] for v in m.vehicles.values() if v['action'] and v['action']['kind']=='water'))
        self.assertEqual(partial['delivered'],saved['zones'][partial['id']]['delivered'])
        m=Mission(contract={'work_deadline':1,'recovery_deadline':4}); m.status='running'
        for _ in range(20): c.step(m); m.tick(.25)
        self.assertEqual(m.status,'failed')
        self.assertFalse(m.verify()['coverage'])

    def test_contract_and_truth_tampering(self):
        m=Mission(); m.contract['target']=1
        self.assertFalse(m.verify()['contract'])
        m=Mission(); m.zones['0:0']['initial']=100
        self.assertFalse(m.verify()['contract'])

    def test_policy_has_no_hidden_moisture(self):
        m=Mission(); obs=m.observations()
        self.assertNotIn('initial',obs['zones'][0]); self.assertIsNone(obs['zones'][0]['observed'])
        self.assertEqual(obs['zones'][0]['required_remaining'],0)
