# CLIProxyAPI per-account exclusion contracts

These opt-in Go tests compile inside a separate, pinned CLIProxyAPI checkout by
using `go test -overlay`. They do not vendor or modify CLIProxyAPI.

## Verified scope

The behavioral test bodies passed against CLIProxyAPI commit
`856ddd8df746a38a6033dbbf6c140974bf5aea0f` on macOS arm64:

- exact wire ID exclusion does not exclude sibling or unrelated IDs;
- explicit wildcard exclusion covers every matching ID and stops at its pattern;
- selection and in-request retry never call an excluded account;
- another eligible account still serves;
- excluding the model on every account preserves `auth_not_found` exhaustion;
- saving and clearing an exclusion changes later selection on the same Manager;
- a per-account alias cannot revive its excluded wire ID;
- actual file writes travel through fsnotify, the real Service update consumer,
  model registration and same-Manager selection without a restart.

The provider executor is the only request-boundary fake. Accounts and tokens are
synthetic. The test does not call a provider.

This scope is native CLIProxyAPI behavior only. It does not validate the
Python-to-Go HTTP boundary from codex-lb to a running CLIProxyAPI process. The
existing executable fixture in
`tests/integration/test_claude_sidecar_excluded_models_contract.py` remains the
opt-in contract for that boundary and is not replaced by these tests.

## Prerequisites

- macOS with `/usr/bin/sandbox-exec` available;
- an installed Go toolchain for darwin/arm64;
- a clean, physical CLIProxyAPI checkout at the pinned commit;
- a physical, pre-populated Go module cache containing every dependency;
- no dependency resolution or download is permitted.

Paths must be absolute and already resolved physically. The checkout Git common
directory may live outside the checkout, such as for a Git worktree. Supply that
physical directory explicitly. The same source, Git, module-cache and repository
values must be bound to both the sandbox policy and the sanitized child.

## Invocation

Substitute existing physical paths directly. Do not add command substitutions,
Git discovery or another shell before `sandbox-exec`:

```bash
/usr/bin/sandbox-exec \
  -D CLIPROXY_SOURCE=/physical/path/to/CLIProxyAPI \
  -D CLIPROXY_GIT=/physical/path/to/CLIProxyAPI-git-common-dir \
  -D GO_MODCACHE=/physical/path/to/go/pkg/mod \
  -D CODEX_LB_REPO=/physical/path/to/codex-lb \
  -f /physical/path/to/codex-lb/tests/contract/cliproxy_exclusions/sandbox.sb \
  /usr/bin/env -i \
    PATH=/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin \
    CODEX_LB_CONTRACT_LAUNCH=1 \
    CLIPROXY_SOURCE=/physical/path/to/CLIProxyAPI \
    CLIPROXY_GIT=/physical/path/to/CLIProxyAPI-git-common-dir \
    GO_MODCACHE=/physical/path/to/go/pkg/mod \
    CODEX_LB_REPO=/physical/path/to/codex-lb \
    GO_BIN=/physical/path/to/go \
    RUN_PARENT=/physical/writable/run-parent \
    /bin/bash --noprofile --norc \
      /physical/path/to/codex-lb/tests/contract/cliproxy_exclusions/run.sh
```

This fixed process order is the supported safe route:

```text
sandbox-exec -> env -i -> /bin/bash --noprofile --norc -> run.sh
```

Do not invoke `run.sh` directly. `CODEX_LB_CONTRACT_LAUNCH` is only a launch-shape
check; it cannot prove sandbox enforcement.

Inside the sanitized child, the runner creates an owned mode-0700 root and sets
private HOME, TMPDIR and XDG directories before Git or Go. It then verifies the
physical paths, Git common directory, pinned revision, clean checkout and absent
overlay targets. The sandbox denies all network operations and writes beneath
the CLIProxyAPI source, its Git common directory, the Go module cache, and this
codex-lb repository. This allow-default policy does not deny writes everywhere
else and does not provide exclusive writable-root confinement. All configured
outputs are nevertheless placed in the fresh private run root.

Go receives `GOPROXY=off`, `GOSUMDB=off`, `GOTOOLCHAIN=local`,
`GOFLAGS=-mod=readonly`, a fresh build cache, and a 120-second test timeout. The
runner rejects zero discovered tests, any missing named RUN/PASS, or any failure
marker. It does not clean or publish outputs.

## Failure meaning

A failed preflight means the environment does not satisfy the contract. Do not
relax the sandbox or enable downloads to make it pass. A failed test establishes
only a mismatch at the pinned native-library contract. It does not diagnose the
codex-lb HTTP boundary.
