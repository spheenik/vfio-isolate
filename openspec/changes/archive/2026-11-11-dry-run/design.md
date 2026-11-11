## Decisions

### Executor dry mode
`Executor.run` in dry mode: no `require_root`, no lock, no `journal.open_for_append`
(it creates the file and trims a truncated tail), no `execute`. For each execution it
calls `can_execute(p, ctx)` and `describe(p, ctx)`, printing `would <text>` lines. Restore
steps skip `can_execute`, as a real restore does. With `-u <file>` it prints
`would record undo in <file>` once. Exit status: 0 if every
precondition passed, 1 at the first failed precondition (message as in a real run,
prefixed `dry run:`), mirroring where a real run would stop.

### describe(p, ctx) -> list[str]
Each action implements it; the base class has no default, and a test checks every
action in `ACTIONS` overrides it. Lines show current → new where the current value can
be read cheaply: `set governor of CPUs 8-15: schedutil -> performance`,
`change affinity of 41 of 57 IRQs (mask 8-15)` (with `-v`: one `IRQ 24: 0-31 -> 0-7,16-31`
line per changing IRQ), `move 312 tasks from / to /host.slice (now)`,
`add 16G in 2M pages (8192) to the pool, now 0; whether the kernel can supply them shows
only in a real run`. `describe_many` describes the executions of one command together.
Unreadable values are printed as `unknown (<reason>)`: permission denied, does not exist, or the
error text.

### Chain overlay
Two things are simulated because they are exact: the existence of cpusets (`ctx` holds
the ones earlier steps would create and delete; a created cpuset exists for later
preconditions and is shown as `(new)`) and cpuset task counts (`move-tasks` and
`cpuset-delete` move them; a count that depends on earlier steps is `(after earlier
steps)`, a move of recorded PIDs makes both counts unknown).

Values (masks, governors, pool sizes, partitions) are not simulated. Each action
declares `touches(p)`, the resource keys it changes, and `reads(p)` (default: the same),
the keys whose current value its precondition or description uses. Keys:
`("cpuset", name)` (cpuset-create/modify/delete), `("isolation",)` (cpuset-modify with a
partition: the kernel's isolated CPUs change), `("workqueue",)` (reads also
`("isolation",)`), `("hugepages", size_kb)`, `("governor", cpu)`, `("irq", n)`,
`("caches",)`. `move-tasks` touches nothing here: only task counts change.
After describing a step the executor adds its `touches` to `ctx.touched`. A later step
whose `reads` meet `ctx.touched` is dependent: `describe` prints the new value and
marks the current one `(after earlier steps)` instead of reading the disk, and a
precondition whose input is dependent is not checked; the preview adds the line
`(precondition checked only in a real run: depends on earlier steps)`. This avoids both
false failures and false passes from stale disk state. `irq-affinity` and
`cpu-governor` batches (one command, or one journal record in a restore preview) never
merge across commands; an IRQ/CPU touched earlier counts as `N depend on earlier steps`.
Restore steps use the same mechanism, applied newest record first. Only dry mode builds
`ctx`; the real path passes `None` and never reads it.

### Isolation tracking
`workqueue-affinity mask|add` refuses while CPUs are in isolated partitions, so a preview
that cannot see an earlier partition step would pass what a real run refuses. `ctx` keeps
`isolated_extra` (CPUs earlier steps put into isolated partitions), `isolation_exact`, and
`partitions` (the type an earlier step set per cpuset; a created cpuset is `member`).
While `isolation_exact`, a later workqueue step refuses with the real message on
`workqueue.read_isolated() | isolated_extra`. Steps that touch `("isolation",)`: cpuset-modify
with `--partition`, with `--cpus` on a partition (disk or earlier step) or on the parent of
one (`has_partition_descendant`), cpuset-delete of a partition, workqueue-affinity. After
such a step `ctx.apply` makes the isolation inexact (`isolation_exact = False`) unless the
action's `overlay` called `note_isolated(cpus)`, which only `cpuset-modify --cpus C
--partition isolated` on a cpuset that is not a partition does. Inexact isolation makes
the workqueue step say `(precondition checked only in a real run: ...)` instead of passing
or refusing.

### Read-only guarantee
`can_execute`, `record_undo` and `describe` must not write. Audit them (e.g. controller
enabling in ancestors happens in `execute` only). Enforced by test: run every README
invocation with `-n` on the fake host, compare a full snapshot of the tree before and
after, assert no journal and no lock file, and that the fake `systemctl` saw only
read-only verbs (`show`, `is-active`, …).

### restore -n
`-n` is a global option and also an option of `restore` (`restore -n FILE`, before FILE).
`restore FILE -n` is a usage error (exit status 2, nothing restored). Reads and validates the journal as a real restore does (ownership checks included;
journals are root-owned 0600, so in practice this needs root) and prints each step,
newest record first, via `describe` of the step's action. Nothing is deleted or
rewritten.

### -u journal checks
`journal.check_for_append(path)` shares its validation with `open_for_append`: the
type/owner/mode rules (`_check_stat`), and header, 0.5.x detection and records
(`_existing_tail`). A real run is root, so the preview expects uid 0 as owner (a file
owned by the previewing user is refused). A truncated last line prints `would drop
truncated last line of <file>` and is not trimmed; a missing parent directory fails with
the real run's message. If the user cannot read the file (root-owned 0600), the preview
prints `would record undo in <file> (existing journal not readable as this user; checked
only in a real run)` and exits 0 for that part.

## Not covered

What only a real run shows: hugepage shortfalls, IRQs the kernel refuses (EIO), tasks
that cannot be moved, kernel rejection of a partition. The output says so where relevant.
