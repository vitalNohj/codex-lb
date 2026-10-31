## 1. Wedge fix
- [x] 1.1 Reproduce the wedge on 70235008a with a session held across a wait on a task that needs a session.
- [x] 1.2 Remove the writer lock from connection checkout; keep the writer section around write transactions only.
- [x] 1.3 Give file SQLite a small reusable pool whose checkout never waits.
- [x] 1.4 Pass the database-session suite, the new regression tests, and a load soak with background schedulers running.
