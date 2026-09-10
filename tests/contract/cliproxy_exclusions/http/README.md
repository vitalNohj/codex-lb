# CLIProxyAPI cross-language HTTP contract

This opt-in contract validates codex-lb's real Python route and
`ClaudeSidecarClient` against CLIProxyAPI's real management handler, Manager and
FileTokenStore. The Go fixture is compiled into a separate pinned CLIProxyAPI
checkout with `go test -overlay`. It does not modify that checkout.

The checked test bodies passed privately against CLIProxyAPI commit
`856ddd8df746a38a6033dbbf6c140974bf5aea0f` on macOS arm64. The test saves an
exclusion for one synthetic account, reads it back through HTTP and from disk,
leaves another account unchanged, clears the exclusion, and checks that API
responses do not expose token fields.

The public launcher below is adapted from that run. It has not itself been
executed. The passed run used the same test bodies, coordinator lifecycle and
fixed-port policy, but machine-specific paths and Python startup-file hashes.

## Scope

This contract starts only a selected Go management-package test with one IPv4
listener and a Python ASGI app without lifespan. It does not start the full
CLIProxyAPI main executable or codex-lb application lifespan. It does not use
live accounts, call a provider, validate production behavior, or exercise an
IPv6 endpoint.

The sandbox selector uses `localhost:<port>`, which can cover operating-system
resolved IPv4 and IPv6 loopback addresses. The fixture bind and Python URL are
explicitly numeric IPv4 `127.0.0.1:<port>`, so only IPv4 was exercised.

## Prerequisites

Supply existing, absolute physical paths. The launcher performs no discovery,
installation, dependency resolution, download, or bootstrap.

- macOS with `/usr/bin/sandbox-exec`;
- a clean CLIProxyAPI checkout at the pinned commit;
- its physical Git common directory;
- an installed darwin/arm64 Go toolchain;
- a pre-populated, read-only Go module cache;
- GNU `timeout` or compatible `gtimeout` with `--signal` and `--kill-after`;
- this repository's existing `.venv`, including pytest, pytest-asyncio and the
  project dependencies;
- the physical base-Python target of `.venv/bin/python`;
- the `.venv/pyvenv.cfg`, site-packages directory, and editable `.pth` file
  whose complete contents are the physical codex-lb repository path;
- exactly the reviewed `_virtualenv.pth`, `a1_coverage.pth`, and editable project
  `.pth` startup files in that site-packages directory;
- one unused fixed port from 1024 through 65535 and a writable physical parent
  for the fresh private run root.

Preserving `.venv/bin/python` as the invocation path is intentional. Do not
replace it with the resolved base-Python target.

## Invocation

Substitute paths and one fixed port directly. Every policy path and port must
match its corresponding sanitized-child value. Do not add discovery or another
shell before `sandbox-exec`.

```bash
/usr/bin/sandbox-exec \
  -D CLIPROXY_SOURCE=/physical/path/to/CLIProxyAPI \
  -D CLIPROXY_GIT=/physical/path/to/CLIProxyAPI-git-common-dir \
  -D GO_MODCACHE=/physical/path/to/go/pkg/mod \
  -D CODEX_LB_REPO=/physical/path/to/codex-lb \
  -D FIXTURE_ADDR=localhost:49152 \
  -f /physical/path/to/codex-lb/tests/contract/cliproxy_exclusions/http/sandbox.sb \
  /usr/bin/env -i \
    PATH=/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin \
    CODEX_LB_HTTP_LAUNCH=1 \
    CLIPROXY_SOURCE=/physical/path/to/CLIProxyAPI \
    CLIPROXY_GIT=/physical/path/to/CLIProxyAPI-git-common-dir \
    GO_MODCACHE=/physical/path/to/go/pkg/mod \
    CODEX_LB_REPO=/physical/path/to/codex-lb \
    GO_BIN=/physical/path/to/go \
    TIMEOUT_BIN=/physical/path/to/gtimeout \
    PYTHON_VENV=/physical/path/to/codex-lb/.venv/bin/python \
    PYTHON_TARGET=/physical/path/to/base/python \
    PYVENV_CFG=/physical/path/to/codex-lb/.venv/pyvenv.cfg \
    PYTHON_SITE_PACKAGES=/physical/path/to/codex-lb/.venv/lib/pythonX.Y/site-packages \
    EDITABLE_PTH=/physical/path/to/codex-lb/.venv/lib/pythonX.Y/site-packages/_editable_impl_codex_lb.pth \
    RUN_PARENT=/physical/writable/run-parent \
    FIXTURE_PORT=49152 \
    /physical/path/to/gtimeout --signal=TERM --kill-after=10s 230s \
      /bin/bash --noprofile --norc \
        /physical/path/to/codex-lb/tests/contract/cliproxy_exclusions/http/run.sh
```

The child creates a mode-0700 run root and private HOME, TMPDIR, XDG, build,
database, auth and evidence paths before Git, Go or Python starts. It verifies
the pinned clean checkout, physical Git directory, backing hashes, Python
invocation target, editable source binding and bounded startup-file set.

Go runs offline with a read-only module cache and local toolchain. Compilation,
fixture and Python stages have finite timeouts and owned process groups. Each
direct child exit is retained separately from confirmed process-group
termination. INT exits 130, TERM exits 143, and an otherwise successful run
becomes nonzero if cleanup cannot confirm every owned group has disappeared.

The policy denies all network operations, then allows bind, inbound and outbound
only through `localhost` on the one supplied port. It denies writes beneath the
CLIProxyAPI source, its Git common directory, the module cache and this
repository. It does not claim exclusive filesystem-write confinement.
