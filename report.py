"""Receipt wrapper for Lean 4.36.0 Comparator. No proof logic lives here."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone

VERSION = '4.36.0'
AXIOMS = {'propext', 'Quot.sound', 'Classical.choice'}
TOOLS = ['lake', 'lean', 'leanexport', 'leanchecker', 'leanchecker-paranoid',
         'lean4lean', 'nanoda_bin', 'con-leche', 'con-ron']
NAME = re.compile(r'[A-Za-z_][A-Za-z_0-9\']*(?:\.[A-Za-z_][A-Za-z_0-9\']*)*\Z')


def sha(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1048576), b''):
            h.update(chunk)
    return h.hexdigest()


def strict_json(path):
    def pairs(items):
        result = {}
        for k, v in items:
            if k in result:
                raise ValueError('duplicate JSON key: ' + k)
            result[k] = v
        return result
    return json.loads(path.read_text(), object_pairs_hook=pairs)


def snapshot(project):
    result = {}
    for root, dirs, files in os.walk(project, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d not in {'.git', '.lake', '__pycache__', 'worktrees'})
        for name in dirs + sorted(files):
            p = Path(root) / name
            if p.is_symlink():
                raise ValueError('source symlinks are unsupported')
        for name in sorted(files):
            p = Path(root) / name
            if name != '.git':
                result[str(p.relative_to(project))] = sha(p)
    return result


def policy(project, path, expected):
    if not re.fullmatch('[0-9a-f]{64}', expected) or sha(path) != expected:
        raise ValueError('approved policy digest does not match')
    p = strict_json(path)
    keys = {'challenge_module', 'solution_module', 'theorem_names', 'permitted_axioms', 'challenge_sha256'}
    if type(p) is not dict or set(p) != keys:
        raise ValueError('unsupported policy fields')
    for k in ['challenge_module', 'solution_module']:
        if type(p[k]) is not str or not NAME.fullmatch(p[k]):
            raise ValueError('invalid module name')
    if p['challenge_module'] == p['solution_module']:
        raise ValueError('challenge and solution must be separate modules')
    names = p['theorem_names']
    if type(names) is not list or not names or any(type(n) is not str or not NAME.fullmatch(n) for n in names) or len(names) != len(set(names)):
        raise ValueError('theorem_names must be nonempty and unique')
    axioms = p['permitted_axioms']
    if type(axioms) is not list or any(type(a) is not str or a not in AXIOMS for a in axioms) or len(axioms) != len(set(axioms)):
        raise ValueError('only standard Lean axioms may be permitted')
    challenge = project / (p['challenge_module'].replace('.', '/') + '.lean')
    if sha(challenge) != p['challenge_sha256']:
        raise ValueError('approved challenge digest does not match')
    if (project / 'lean-toolchain').read_text().strip() != 'leanprover/lean4:v' + VERSION:
        raise ValueError('unsupported toolchain; expected Lean ' + VERSION)
    manifest = strict_json(project / 'lake-manifest.json')
    if type(manifest.get('packages')) is not list:
        raise ValueError('manifest packages must be a list')
    for dep in manifest['packages']:
        if dep.get('type') != 'git' or not re.fullmatch('[0-9a-f]{40}', dep.get('rev', '')):
            raise ValueError('dependencies must use full Git commit revisions')
    return p, challenge


def execute(command, cwd, env, log, timeout, max_log=16 * 1024 * 1024):
    start = time.monotonic()
    reason = None
    with open(log, 'wb') as f:
        proc = subprocess.Popen(command, cwd=cwd, env=env, stdout=f,
                                stderr=subprocess.STDOUT, start_new_session=True)
        while proc.poll() is None:
            if time.monotonic() - start > timeout:
                reason = 'timeout'
            elif log.stat().st_size > max_log:
                reason = 'log_limit'
            if reason:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait()
                break
            time.sleep(0.05)
    return {'command': command, 'exit_code': proc.returncode,
            'duration_seconds': round(time.monotonic() - start, 3),
            'interruption': reason, 'log': log.name, 'log_sha256': sha(log)}


def run(args):
    project = Path(args.project).resolve()
    output = Path(args.output).resolve()
    if output == project or project in output.parents:
        raise ValueError('output must be outside the proof project')
    output.mkdir(parents=True, exist_ok=False)
    receipt = {'schema_version': 1, 'status': 'error',
               'started_at': datetime.now(timezone.utc).isoformat(),
               'toolchain': 'leanprover/lean4:v' + VERSION,
               'runner_sha256': sha(__file__),
               'scope': 'Comparator acceptance of named statements; not human interpretation or application-code correctness',
               'run_url': None}
    if os.getenv('GITHUB_ACTIONS') == 'true':
        receipt['run_url'] = 'https://github.com/' + os.environ['GITHUB_REPOSITORY'] + '/actions/runs/' + os.environ['GITHUB_RUN_ID']
    exit_code = 2
    try:
        if not 0 < args.timeout <= 86400:
            raise ValueError('timeout must be in (0, 86400] seconds')
        p, challenge = policy(project, project / args.policy, args.policy_sha256)
        receipt['policy'] = p
        receipt['policy_sha256'] = args.policy_sha256
        (output / 'policy.json').write_bytes((project / args.policy).read_bytes())
        (output / 'Challenge.lean').write_bytes(challenge.read_bytes())
        before = snapshot(project)
        receipt['source_files_sha256'] = before
        git_env = {'PATH': '/usr/bin:/bin', 'HOME': str(output), 'LANG': 'C.UTF-8', 'GIT_CONFIG_NOSYSTEM': '1'}
        receipt['source_commit'] = subprocess.check_output(['git', '-C', str(project), 'rev-parse', 'HEAD'], env=git_env, text=True).strip()
        receipt['source_dirty'] = bool(subprocess.check_output(['git', '-C', str(project), 'status', '--porcelain', '--', '.'], env=git_env, text=True).strip())
        bindir = Path(args.toolchain_bin).resolve()
        receipt['tool_binaries_sha256'] = {name: sha(bindir / name) for name in TOOLS}
        env = {'PATH': str(bindir) + ':/usr/bin:/bin', 'HOME': str(output), 'LANG': 'C.UTF-8', 'TMPDIR': '/tmp'}
        receipt['lean_version'] = subprocess.check_output([str(bindir / 'lean'), '--version'], env=env, text=True, timeout=15).strip()
        if not re.search(r'\bversion 4\.36\.0\b', receipt['lean_version']):
            raise ValueError('installed Lean version does not match pin')
        config = {k: v for k, v in p.items() if k != 'challenge_sha256'}
        cfg = output / 'comparator.json'
        cfg.write_text(json.dumps(config, indent=2) + '\n')
        cmd = [str(bindir / 'lake'), '--no-ansi', 'comparator', '--config', str(cfg), '--paranoid']
        receipt['required_checks'] = ['statement_match', 'permitted_axioms', 'Lean kernel', 'leanchecker-paranoid', 'lean4lean', 'nanoda_bin', 'con-leche', 'con-ron']
        result = execute(cmd, project, env, output / 'comparator.log', args.timeout)
        receipt['comparator'] = result
        after = snapshot(project)
        receipt['inputs_unchanged'] = before == after
        if result['interruption']:
            receipt['status'] = 'incomplete'
            exit_code = 124
        elif before != after:
            receipt['status'] = 'error'
            receipt['error'] = 'project inputs changed during verification'
        elif result['exit_code'] == 0:
            receipt['status'] = 'accepted'
            exit_code = 0
        elif result['exit_code'] == 1:
            receipt['status'] = 'failed'
            exit_code = 1
        else:
            receipt['status'] = 'error'
    except (ValueError, OSError, subprocess.SubprocessError, KeyError, TypeError) as exc:
        receipt['error'] = str(exc)
    finally:
        (output / 'report.json').write_text(json.dumps(receipt, indent=2) + '\n')
        # User-controlled names stay in JSON, never injected into Markdown/HTML.
        lines = ['# Proof report', '', 'Status: **' + receipt['status'] + '**', '',
                 'Lean: ' + VERSION, '',
                 'See report.json for the exact policy, source hashes and execution receipt.', '',
                 'Accepted means Comparator returned success with all required checks enabled. Failure may mean a rejected proof or a build failure. This report is not a signed attestation or an independent proof.', '']
        (output / 'report.md').write_text('\n'.join(lines))
        files = ['report.json', 'report.md'] + [n for n in ['policy.json', 'Challenge.lean', 'comparator.json', 'comparator.log'] if (output / n).exists()]
        (output / 'SHA256SUMS').write_text(''.join(sha(output / n) + '  ' + n + '\n' for n in files))
        if os.getenv('GITHUB_STEP_SUMMARY'):
            with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as f:
                f.write((output / 'report.md').read_text())
    return exit_code


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--project', required=True)
    parser.add_argument('--policy', default='proof-policy.json')
    parser.add_argument('--policy-sha256', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--toolchain-bin', default='/opt/lean/bin')
    parser.add_argument('--timeout', type=float, default=600)
    try:
        sys.exit(run(parser.parse_args()))
    except (ValueError, OSError) as exc:
        print('proof-report: ' + str(exc), file=sys.stderr)
        sys.exit(2)
