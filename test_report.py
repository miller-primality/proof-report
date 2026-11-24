import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from fixtures import create
from report import policy, execute, snapshot, sha

class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)/'project'
        self.digest = create(self.root,'valid')
        self.path = self.root/'proof-policy.json'
    def tearDown(self): self.temp.cleanup()
    def update(self, **changes):
        p=json.loads(self.path.read_text()); p.update(changes)
        self.path.write_text(json.dumps(p)); self.digest=sha(self.path)
    def check(self): return policy(self.root,self.path,self.digest)
    def test_valid(self): self.assertEqual(self.check()[0]['theorem_names'],['identity'])
    def test_policy_tampering(self):
        self.path.write_text(self.path.read_text()+' ')
        with self.assertRaises(ValueError): self.check()
    def test_statement_tampering(self):
        (self.root/'Challenge.lean').write_text('theorem identity : True := by trivial')
        with self.assertRaises(ValueError): self.check()
    def test_empty_claim(self):
        self.update(theorem_names=[])
        with self.assertRaises(ValueError): self.check()
    def test_custom_axiom(self):
        self.update(permitted_axioms=['sorryAx'])
        with self.assertRaises(ValueError): self.check()
    def test_custom_checker(self):
        self.update(external_kernels={'fake':['true']})
        with self.assertRaises(ValueError): self.check()
    def test_duplicate_json(self):
        self.path.write_text('{"a":1,"a":2}'); self.digest=sha(self.path)
        with self.assertRaises(ValueError): self.check()
    def test_unpinned_dependency(self):
        (self.root/'lake-manifest.json').write_text('{"packages":[{"type":"git","rev":"main"}]}')
        with self.assertRaises(ValueError): self.check()
    def test_symlink(self):
        (self.root/'external').symlink_to('/tmp',target_is_directory=True)
        with self.assertRaises(ValueError): snapshot(self.root)
    def test_timeout(self):
        r=execute([sys.executable,'-c','import time; time.sleep(20)'],self.root,{},Path(self.temp.name)/'log',.05)
        self.assertEqual(r['interruption'],'timeout'); self.assertNotEqual(r['exit_code'],0)
    def test_failure_receipt(self):
        r=execute([sys.executable,'-c','print("not a proof"); raise SystemExit(1)'],self.root,{},Path(self.temp.name)/'log',5)
        self.assertEqual(r['exit_code'],1); self.assertIsNone(r['interruption'])
    def test_log_limit(self):
        r=execute([sys.executable,'-c','import sys,time; print("x"*10000,flush=True); time.sleep(20)'],self.root,{},Path(self.temp.name)/'log',5,100)
        self.assertEqual(r['interruption'],'log_limit')

if __name__=='__main__': unittest.main()
