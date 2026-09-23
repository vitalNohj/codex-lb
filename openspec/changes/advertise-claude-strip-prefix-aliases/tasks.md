## 1. Catalog

- [x] 1.1 Advertise a Claude strip-prefix alias when dispatch returns the upstream id the alias names.
- [x] 1.2 Omit an alias whose model profile rewrites that upstream id.

## 2. Validation

- [x] 2.1 `openspec validate advertise-claude-strip-prefix-aliases --strict`
- [x] 2.2 Integration test: `cc/claude-opus-5-5` is listed and a chat request forwards `claude-opus-5-5`.
