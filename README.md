# proof-report

GitHub Action for reproducible Lean proof-checking receipts. Uses Lean 4.36.0
Comparator with its sandbox and all bundled checkers enabled. MIT licensed.

## Output

- JSON verdict, exact theorem names and permitted axioms
- Approved challenge source and policy
- Source, dependency-manifest and tool-binary hashes
- Comparator exit code, duration and full log
- Markdown summary and SHA-256 file manifest

`accepted` means Comparator accepted the named statements. `failed` includes
proof rejection and build failure. `incomplete` means timeout or log limit.
`error` means setup or input validation failed. Only `accepted` exits zero.

## Use

Requires Linux, bubblewrap, Python 3 and the official Lean 4.36.0 toolchain.
Supply a fresh checkout with a committed `lake-manifest.json`. Git dependencies
must use full commit revisions. Path dependencies and custom checkers are unsupported.

```yaml
permissions:
  contents: read
steps:
  - uses: actions/checkout@v4
    with:
      persist-credentials: false
  # Install the pinned toolchain and bubblewrap; see the CI workflow.
  - uses: miller-primality/proof-report@<reviewed-commit-sha>
    with:
      project: ./proof
      policy-sha256: <maintainer-approved-policy-sha256>
      output: ${{ runner.temp }}/proof-report
  - uses: actions/upload-artifact@v4
    if: always()
    with:
      name: proof-report
      path: ${{ runner.temp }}/proof-report
```

`proof-policy.json`:

```json
{
  "challenge_module": "Challenge",
  "solution_module": "Solution",
  "theorem_names": ["identity"],
  "permitted_axioms": ["propext", "Quot.sound", "Classical.choice"],
  "challenge_sha256": "<sha256-of-Challenge.lean>"
}
```

Review the challenge and its imports before approving the policy digest.
Do not derive approval from a solver-controlled pull request. Definition holes
and nonstandard axioms are unsupported. Protect the workflow and action revision too.

## Scope

This wraps existing checkers; it is not a new kernel or a formal proof of the
reporting code. Permitted axioms are a policy, not a list of observed dependencies.
The checker receipt is aggregate; the log retains individual checker output.

A passed check does not establish that the statement expresses the intended
mathematics, that application code implements it, or that the runner is trustworthy.
Hashes support reproducibility and corruption detection, not authenticity.
Reports are unsigned. Run on disposable runners without secrets; retain Lean's
sandbox. Dependency fetching may access the network; the comparator build/check
stages use its sandbox. Never pre-build untrusted proof code outside it.

## Development

`python3 -m unittest -v test_report.py`

CI also checks a valid proof, statement mismatch, `sorry`, and an extra axiom
using real Lean kernels. No large theorem verification is claimed.

Issues and focused patches are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md).
