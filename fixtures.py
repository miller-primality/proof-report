"""Create disposable integration projects. Not part of the verification action."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys


def create(root, case):
    root = Path(root)
    root.mkdir(parents=True)
    challenge = 'theorem identity (n : Nat) : n + 0 = n := by sorry\n'
    solutions = {
        'valid': 'theorem identity (n : Nat) : n + 0 = n := by rfl\n',
        'mismatch': 'theorem identity : True := True.intro\n',
        'sorry': 'theorem identity (n : Nat) : n + 0 = n := by sorry\n',
        'axiom': 'axiom backdoor : False\ntheorem identity (n : Nat) : n + 0 = n := False.elim backdoor\n',
    }
    (root / 'Challenge.lean').write_text(challenge)
    (root / 'Solution.lean').write_text(solutions[case])
    (root / 'lean-toolchain').write_text('leanprover/lean4:v4.36.0\n')
    (root / 'lakefile.toml').write_text('name = "proof_fixture"\nversion = "0.1.0"\n[[lean_lib]]\nname = "Challenge"\n[[lean_lib]]\nname = "Solution"\n')
    (root / 'lake-manifest.json').write_text(json.dumps({'version': '1.1.0', 'packagesDir': '.lake/packages', 'packages': [], 'name': 'proof_fixture', 'lakeDir': '.lake'}))
    (root / '.gitignore').write_text('.lake/\n')
    policy = {'challenge_module': 'Challenge', 'solution_module': 'Solution', 'theorem_names': ['identity'], 'permitted_axioms': ['propext','Quot.sound','Classical.choice'], 'challenge_sha256': hashlib.sha256(challenge.encode()).hexdigest()}
    (root / 'proof-policy.json').write_text(json.dumps(policy, indent=2) + '\n')
    for command in [['init','-q'],['add','.'],['-c','user.name=Fixture','-c','user.email=fixture@example.invalid','commit','-qm','Fixture']]:
        subprocess.run(['git','-C',str(root),*command],check=True)
    return hashlib.sha256((root / 'proof-policy.json').read_bytes()).hexdigest()


if __name__ == '__main__':
    print(create(sys.argv[1],sys.argv[2]))
