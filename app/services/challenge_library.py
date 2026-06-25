"""Extended library of senior, build-from-scratch coding challenges.

These are NOT seeded automatically. They form a curated catalogue of HARD
distributed-systems / data / platform problems that an organization can add
to its project set. Each challenge mirrors the structure of
``app/services/default_projects.py``: a markdown problem statement plus a
bespoke, anchored rubric (each dimension scored at 2 / 5 / 8 / 10).

Every problem is designed for a build-from-scratch session: the CLI does not
deliver starter files, so problem statements never reference a "provided"
repo or scaffold. Candidates scaffold the project themselves and, where a
simulated cluster / corpus / load is needed, generate it as part of their work.

The single source of truth for the catalogue is ``CHALLENGE_LIBRARY``.
"""

from __future__ import annotations


def _band(rule: str, b2: str, b5: str, b8: str, b10: str) -> str:
    """Format a rubric dimension with explicit scoring anchors at 2/5/8/10."""
    return (
        f"{rule} "
        f"**2/10**: {b2} "
        f"**5/10**: {b5} "
        f"**8/10**: {b8} "
        f"**10/10**: {b10}"
    )


# =========================================================================
# HARD — Distributed Systems Engineer (consensus)
# =========================================================================

RAFT_PROBLEM = """\
# Raft-Lite Log Replication

Build **Quorum**, a miniature replicated log built on a Raft-style consensus
core: leader election, append-entries replication, and a commit index that
advances only when an entry is durably stored on a majority. You are starting
from an empty directory — pick your language and scaffold everything yourself.

There is **no real network**. As part of your work, build an in-process
simulated cluster of `N` nodes (default 5) that pass messages through a
**controllable transport** you write. The transport must let a test:

- drop, delay, duplicate, or reorder individual messages;
- partition the cluster into arbitrary subsets and later heal the partition;
- advance a logical clock so election timeouts and heartbeats are
  deterministic (no `sleep`-based flakiness).

## What to build

1. **Node state machine** implementing the three roles — follower,
   candidate, leader — with `currentTerm`, `votedFor`, and a persistent
   `log[]` of `(term, command)` entries per node.
2. **Leader election.** Randomized election timeouts; a candidate that wins a
   majority of votes in its term becomes leader and starts sending
   heartbeats. A node grants at most one vote per term and never votes for a
   candidate whose log is less up-to-date than its own.
3. **Append-entries replication.** The leader replicates client commands to
   followers, tracks `nextIndex` / `matchIndex` per follower, and backs up
   `nextIndex` on rejection to repair divergent follower logs.
4. **Commit + apply.** An entry is committed once it is stored on a majority
   *and* is from the leader's current term; committed entries are applied to a
   per-node key-value state machine in log order. Expose
   `propose(command) -> {committed: bool, index, term}` and a way to read each
   node's applied state.
5. **Persistence across crashes.** `currentTerm`, `votedFor`, and the log
   survive a simulated crash + restart of a node. A restarted node must not
   violate any safety rule (e.g., must not vote twice in one term).
6. **A test harness** (your own, deterministic) that drives the scenarios
   under *What we will do to it*, asserting safety after each.

## What we care about (senior signal)

- **Safety under partition.** A command reported committed must remain
  committed and identical on every node after the partition heals — it is
  never lost, reordered, or silently rewritten.
- **Correct term/leader rules.** Two leaders never coexist in the same term;
  a stale leader returning from a partition steps down on seeing a higher
  term and does not corrupt committed history.
- **Election liveness.** When a majority can communicate, a leader is elected
  within a bounded number of timeouts; split votes resolve rather than
  livelock forever.

## What we will do to it

We will partition the leader away from a majority and confirm a new leader is
elected; let the old leader keep accepting writes in its minority partition,
then heal and confirm those uncommitted writes are discarded while every
*committed* entry survives identically everywhere; crash and restart followers
mid-replication; and run a randomized fuzz of drops/delays/partitions while
asserting the log-matching and state-machine-safety invariants hold after
every step.

## Out of scope

- Snapshotting / log compaction (a bounded in-memory log is fine).
- Dynamic cluster membership changes (fixed `N`).
- A real socket transport, RPC framework, or persistence engine — your own
  in-process transport and a file/JSON log are fine.
- Authentication, a UI, client-side retries.
"""

RUBRIC_RAFT = [
    {
        "name": "Election Safety and Term Rules",
        "weight": 10,
        "description": _band(
            "At most one leader per term; term and voting rules are never violated.",
            "Multiple nodes can declare themselves leader in the same term; term not advanced on vote.",
            "Single leader on the happy path, but a node can grant two votes in one term or a stale-term message is acted on instead of rejected.",
            "One vote per term enforced via persisted votedFor; higher-term messages always win and force a step-down; candidates require a strict majority.",
            "Above + the up-to-date-log vote restriction is correct (last-term then last-index), proven by a test where a node with a shorter log is denied the vote; two-leaders-per-term is shown impossible under a partition.",
        ),
    },
    {
        "name": "Commit Safety Under Partition",
        "weight": 10,
        "description": _band(
            "A committed entry is never lost, reordered, or overwritten after a partition heals.",
            "An entry reported committed can disappear or change value after the partition heals.",
            "Commits survive simple cases but a minority-partition leader's writes can overwrite a committed entry, or commit advances on a majority of stores without the current-term rule.",
            "Commit requires majority replication AND an entry of the leader's current term; uncommitted minority writes are discarded on heal while every committed entry survives identically.",
            "Above + the commit rule is demonstrably correct under the classic Figure-8 scenario (a leader does not treat a prior-term entry as committed on replication count alone); a randomized partition fuzz never loses a committed entry.",
        ),
    },
    {
        "name": "Log Replication and Repair",
        "weight": 9,
        "description": _band(
            "Diverged follower logs are repaired to match the leader exactly.",
            "Leader appends blindly; a follower with a conflicting suffix is never reconciled.",
            "nextIndex/matchIndex tracked and consistent logs replicate, but rejection does not back up nextIndex so a diverged follower stays stuck.",
            "Consistency check on (prevLogIndex, prevLogTerm); rejection backs up nextIndex and overwrites the follower's conflicting suffix; matchIndex drives commit.",
            "Above + the Log Matching Property holds after fuzzing (same index+term ⇒ identical prefix everywhere); backup is at least batched/bounded rather than one-index-per-round on long divergences.",
        ),
    },
    {
        "name": "Crash Recovery and Persistence",
        "weight": 8,
        "description": _band(
            "currentTerm, votedFor, and the log survive crash + restart without breaking safety.",
            "All state is in memory; a restart resets term/votedFor and the node re-votes in a term it already voted in.",
            "Log persisted but term/votedFor are not, so a restarted node can grant a second vote in the same term.",
            "currentTerm, votedFor, and log persisted and reloaded; a restarted node rejoins without violating election or commit safety.",
            "Above + persistence ordering is correct (state durable before the corresponding RPC reply is sent), shown by a crash injected between append and ack that does not lose an acknowledged entry.",
        ),
    },
    {
        "name": "Deterministic Simulation Harness",
        "weight": 7,
        "description": _band(
            "The cluster runs on a controllable transport + logical clock, not wall-clock sleeps.",
            "Real threads and sleep()-based timeouts; tests are flaky and timing-dependent.",
            "A message bus exists but timeouts use wall-clock, so partition/heal scenarios are racy and not reproducible.",
            "Logical clock drives all timeouts; transport can drop/delay/reorder/partition deterministically; a seed reproduces a run exactly.",
            "Above + invariants (one-leader-per-term, log-matching, state-machine-safety) are asserted automatically after every step of a seeded randomized fuzz.",
        ),
    },
    {
        "name": "Election Liveness",
        "weight": 6,
        "description": _band(
            "When a majority can communicate, a leader emerges in bounded time.",
            "Cluster can deadlock with no leader even when all nodes can talk.",
            "Elects a leader normally but repeated split votes can livelock because timeouts are not randomized.",
            "Randomized timeouts break ties; a leader is elected within a bounded number of rounds once a majority is connected.",
            "Above + leadership is stable (no needless churn under steady heartbeats) and re-election after leader loss is bounded and demonstrated.",
        ),
    },
    {
        "name": "Code Structure and Invariant Clarity",
        "weight": 5,
        "description": _band(
            "Roles, RPC handling, and the state machine are cleanly separated and the invariants are legible.",
            "One giant loop mixes transport, role transitions, and the KV state machine; safety rules are implicit.",
            "Roles separated but RPC handlers mutate shared state without a clear single owner of term/log transitions.",
            "Clear role transitions, one place that owns term/vote/commit updates, the applied state machine isolated from consensus.",
            "Above + invariants named in code/comments and checkable; a reader can point to where each Raft safety property is enforced.",
        ),
    },
]


# =========================================================================
# HARD — Real-Time / Collaboration Engineer (CRDT)
# =========================================================================

CRDT_PROBLEM = """\
# CRDT Collaborative Text Buffer

Build **Coalesce**, a conflict-free replicated text buffer that lets several
replicas edit the same document concurrently — fully offline if needed — and
**converge** to the same text once they exchange operations, with no central
server and no operational-transform-style rebasing. You are starting from an
empty directory; pick your language and scaffold everything yourself.

Implement a sequence CRDT (RGA, LSEQ, Logoot, or Fugue-style — your choice;
justify it). There is **no network**: build an in-process harness where each
replica has an outbound op stream you can deliver to other replicas in any
order, with arbitrary delays and duplicates.

## What to build

1. **Replica API** with a stable replica id:
   - `insert(index, text)` — insert at a *visible* character position.
   - `delete(index, length)` — delete a run of visible characters.
   - `value() -> str` — the current visible text.
   - `emit() -> [op...]` and `apply(op)` — produce and consume the ops other
     replicas need; `apply` must be **idempotent** and **commutative**.
2. **Stable element identity.** Each inserted character has a globally unique,
   immutable id with a total order, so concurrent inserts at the same visible
   position resolve to the *same* interleaving on every replica.
3. **Tombstones for deletes.** A deleted character is tombstoned, not removed
   from the structure, so a concurrent insert that referenced it still lands
   in the right place; tombstones never reappear as visible text.
4. **Convergence.** Given the same set of ops delivered in any order (with
   duplicates), all replicas reach byte-identical `value()`. Causal delivery
   may be assumed *only* if you implement and enforce it explicitly
   (e.g., version vectors); otherwise ops must be safe to apply out of order.
5. **A test harness** (your own, deterministic, seeded) that spins up `k`
   replicas, applies randomized interleaved edits, shuffles op delivery, and
   asserts convergence + intention-preservation invariants.

## What we care about (senior signal)

- **Convergence.** No delivery order, duplication, or split-and-merge of op
  batches can leave two replicas with different visible text once they have
  seen the same ops.
- **Intention preservation.** "Insert X between A and B" still places X
  between A and B even if B was concurrently deleted or another replica
  inserted Y at the same spot; concurrent inserts at one position interleave
  deterministically rather than clobbering each other.
- **Tombstone discipline.** Deletes are idempotent, a re-delivered delete is a
  no-op, and tombstoned ids are never resurrected or double-counted in
  position math.

## What we will do to it

We will run two replicas making concurrent inserts at the *same* index and
confirm both converge to the same interleaving; delete a character on one
replica while another inserts immediately after it, then merge; deliver the
same op batch twice and in reverse order; and fuzz `k` replicas with thousands
of shuffled ops, asserting `value()` is identical everywhere and equals a
reference linearization.

## Out of scope

- Rich text / formatting attributes — plain characters only.
- A real network or persistence layer — your in-process op delivery is fine.
- Garbage-collecting tombstones across replicas (you may discuss it, but a
  growing tombstone set is acceptable for this exercise).
- A UI or cursor/presence sharing.
"""

RUBRIC_CRDT = [
    {
        "name": "Convergence Under Reordering and Duplication",
        "weight": 10,
        "description": _band(
            "Replicas reach byte-identical text given the same ops in any order, with duplicates.",
            "Replicas diverge under reordering; final text depends on delivery order.",
            "Converges when ops arrive in order, but a reordered or duplicated op produces different text on different replicas.",
            "apply() is commutative and idempotent; converges under arbitrary order and duplicate delivery in tests.",
            "Above + a seeded fuzz of k replicas with thousands of shuffled/duplicated ops converges to a single reference linearization every run.",
        ),
    },
    {
        "name": "Element Identity and Ordering",
        "weight": 9,
        "description": _band(
            "Every character has a unique, immutable id with a deterministic total order.",
            "Positions are array indices; identity shifts as the document changes, so concurrent edits clash.",
            "Ids exist but ties between concurrent inserts are broken nondeterministically (e.g., by arrival time), so interleaving differs per replica.",
            "Globally unique immutable ids with a stable total order; concurrent inserts at one spot interleave identically everywhere via (position, replica-id) tie-break.",
            "Above + id allocation avoids pathological growth/interleaving (LSEQ-style allocation or RGA references documented), and the ordering choice is justified against alternatives.",
        ),
    },
    {
        "name": "Intention Preservation",
        "weight": 9,
        "description": _band(
            "An insert lands between the intended neighbors even under concurrent edits/deletes.",
            "Insert position is recomputed from a stale visible index, so concurrent edits move the character to the wrong place.",
            "Anchors to a neighbor id but breaks when that neighbor was concurrently deleted (insert is dropped or misplaced).",
            "Inserts anchor to immutable element ids, so they land between the intended elements even if a neighbor is concurrently tombstoned.",
            "Above + concurrent inserts at the same anchor produce a deterministic, non-interleaved-garbled result that matches the documented merge semantics; demonstrated by the same-index concurrent-insert test.",
        ),
    },
    {
        "name": "Tombstone and Delete Discipline",
        "weight": 8,
        "description": _band(
            "Deletes are idempotent; tombstones never reappear and never corrupt position math.",
            "Delete physically removes the element, so a concurrent insert referencing it is lost or misplaced.",
            "Tombstones exist but a re-delivered delete double-acts, or tombstoned elements are counted in visible-index math.",
            "Deletes tombstone elements idempotently; re-delivered deletes are no-ops; visible-index translation skips tombstones correctly.",
            "Above + a delete arriving before the matching insert is handled safely (no resurrection, no crash), and tombstone state is consistent across replicas after merge.",
        ),
    },
    {
        "name": "Causal / Out-of-Order Delivery Handling",
        "weight": 7,
        "description": _band(
            "The system is explicit and correct about causal dependencies between ops.",
            "Silently assumes in-order delivery; an op referencing an unseen element crashes or corrupts state.",
            "Assumes causal delivery but does not enforce or document it, so the harness can feed an order that breaks it.",
            "Either ops are genuinely order-independent, or causal delivery is enforced (version vectors / buffering of premature ops) and documented.",
            "Above + premature ops are buffered and applied when dependencies arrive, exercised by a test that delivers a child op before its parent.",
        ),
    },
    {
        "name": "Deterministic Concurrency Harness",
        "weight": 6,
        "description": _band(
            "A seeded harness drives k replicas with controllable, reproducible op delivery.",
            "No harness; correctness shown only by ad-hoc manual edits.",
            "A harness exists but delivery order is not controllable or not reproducible from a seed.",
            "Seeded harness shuffles, delays, and duplicates op delivery across k replicas reproducibly.",
            "Above + convergence and intention invariants are asserted automatically after every merge, and a failing seed is reproducible for debugging.",
        ),
    },
    {
        "name": "Performance and Memory Behavior",
        "weight": 5,
        "description": _band(
            "Edit and merge costs are reasonable and the data structure does not blow up needlessly.",
            "Every insert/delete is O(n) over the whole document or rebuilds the structure; trivially slow.",
            "Works on small docs but visible-index lookups are linear with no thought to large documents.",
            "Insert/delete/lookup are sub-linear or clearly bounded; op size is small; tombstone growth is acknowledged.",
            "Above + a benchmark shows acceptable behavior on a large doc with many edits, and the candidate names the tombstone-GC trade-off they deferred.",
        ),
    },
]


# =========================================================================
# HARD — Data / Observability Engineer (time-series)
# =========================================================================

TSDB_PROBLEM = """\
# Time-Series Metrics Store

Build **Tessera**, an embeddable time-series metrics store that ingests
high-rate numeric points, rolls them up into fixed-resolution aggregates,
enforces retention, and answers range queries — all under a **bounded memory
budget**. You are starting from an empty directory; pick your language and
scaffold everything yourself.

A point is `(metric, labels, timestamp_ms, value)`. The store is configured
with a set of **rollup levels**, e.g.:

- raw → 10s buckets, kept 1 hour
- 10s → 1m buckets, kept 6 hours
- 1m → 1h buckets, kept 30 days

Each rollup bucket holds aggregates: `count, sum, min, max, last` (enough to
answer avg, sum, min, max, rate over a range).

## What to build

1. **Ingest** `write(metric, labels, ts_ms, value)` at high rate. Points may
   arrive **out of order** and **late** (a point whose timestamp lands in an
   already-rolled-up window). Define and implement a clear, bounded
   late-arrival policy.
2. **Downsampling / rollups.** Raw points fold into the smallest bucket; each
   level folds into the next coarser level. Aggregation across a rollup
   boundary must be correct: rolling 10s→1m must produce the same `min/max/sum`
   as aggregating the underlying raw points directly.
3. **Retention.** Each level has a max age; expired buckets are evicted so
   memory stays bounded regardless of how long the process runs. Eviction must
   not corrupt in-flight queries.
4. **Range queries** `query(metric, labels_matcher, from_ms, to_ms, step_ms)
   -> [(bucket_ts, aggregate)...]`. The store picks the appropriate rollup
   level for the requested `step`, aligns buckets to step boundaries, and
   returns gaps explicitly (no fabricated zero-fill unless asked).
5. **Bounded memory.** Given a fixed cardinality and retention, steady-state
   memory must be bounded and predictable; describe the bound. A pathological
   client that writes ever-new label sets must be contained (cardinality cap or
   documented policy), not allowed to OOM the process.
6. **A benchmark / harness** you write that ingests a high-rate synthetic
   stream (out-of-order included) and reports ingest throughput and steady
   memory.

## What we care about (senior signal)

- **Bounded memory.** Memory reaches a steady state and stays there; rollup
  and retention reclaim space; cardinality is contained.
- **Correct aggregation across rollup boundaries.** A query answered from a
  coarse rollup returns the same min/max/sum/avg as if computed from raw
  points for any range, including ranges that straddle bucket boundaries.
- **Late-arriving points.** A late point updates the correct historical bucket
  (and its coarser parents) if still within retention, or is rejected/counted
  per a clear policy if too old — never silently dropped without a counter.

## What we will do to it

We will write points out of order and across rollup boundaries, then compare
a coarse-rollup query against a brute-force aggregation of the raw points;
fire a point that is 2 hours late and confirm it lands in the right bucket or
is rejected per your stated policy with a counter incremented; let the process
run long enough that retention must evict, and confirm memory plateaus; and
blast new label combinations to confirm cardinality is bounded.

## Out of scope

- On-disk persistence / WAL — an in-memory store is fine (but design as if it
  could be flushed).
- A query language (PromQL etc.) — a typed `query()` call is enough.
- Distribution / sharding across nodes.
- A UI or HTTP layer (a library API is fine; a thin CLI is welcome).
"""

RUBRIC_TSDB = [
    {
        "name": "Rollup Aggregation Correctness",
        "weight": 10,
        "description": _band(
            "Coarse-rollup queries match brute-force aggregation of raw points, including across bucket boundaries.",
            "Rollups store only avg (or recompute avg-of-avg), so sum/min/max are wrong from coarse levels.",
            "min/max/sum correct within a level, but folding one level into the next loses precision or mishandles boundary-straddling ranges.",
            "Each bucket keeps count/sum/min/max/last; level-to-level folding is exact; queries align to step boundaries and match raw aggregation.",
            "Above + avg/rate derived correctly from stored aggregates, demonstrated equal to a brute-force computation over randomized ranges that straddle boundaries.",
        ),
    },
    {
        "name": "Bounded Memory and Retention",
        "weight": 10,
        "description": _band(
            "Steady-state memory is bounded and predictable; retention reclaims space without corrupting queries.",
            "All points retained forever; memory grows without bound.",
            "Retention exists but eviction is ad-hoc (e.g., on query) so memory sawtooths unpredictably or a concurrent query sees half-evicted buckets.",
            "Per-level retention evicts expired buckets; steady-state memory plateaus; eviction does not corrupt in-flight queries.",
            "Above + the memory bound is stated as a formula of cardinality × buckets-per-level, and a long-running benchmark shows the plateau matching the bound.",
        ),
    },
    {
        "name": "Late and Out-of-Order Point Handling",
        "weight": 9,
        "description": _band(
            "Late/out-of-order points update the correct historical buckets per a clear, bounded policy.",
            "Assumes monotonic timestamps; an out-of-order point lands in the wrong bucket or corrupts the current one.",
            "Out-of-order within the current window works, but a point landing in an already-rolled-up bucket is silently dropped with no counter.",
            "Late points update the correct historical bucket and propagate to coarser parents if within retention; too-old points rejected per a stated policy and counted.",
            "Above + the late-arrival horizon is configurable and documented, and a 2-hour-late point is shown to either correctly update parents or be rejected-with-counter exactly as specified.",
        ),
    },
    {
        "name": "Cardinality Containment",
        "weight": 8,
        "description": _band(
            "A flood of new label sets cannot OOM the process.",
            "Every distinct label set allocates unbounded series; a label-cardinality attack OOMs the store.",
            "Series tracked in a map with no cap; memory grows with cardinality and there is no policy.",
            "Cardinality is capped or bounded by a documented policy (reject/drop/aggregate-into-overflow) with a counter when the cap is hit.",
            "Above + the policy is tested under a new-label flood and memory stays bounded; the trade-off (rejection vs. overflow series) is justified.",
        ),
    },
    {
        "name": "Query Semantics and Alignment",
        "weight": 7,
        "description": _band(
            "Queries pick the right rollup, align to step boundaries, and represent gaps honestly.",
            "Query scans raw points regardless of step, or returns misaligned/overlapping buckets.",
            "Returns data but always from one level regardless of requested step, or fabricates zero-fill that hides real gaps.",
            "Selects the appropriate rollup for the step, aligns buckets to step boundaries, and returns gaps explicitly rather than fabricating values.",
            "Above + step coarser/finer than any stored level is handled sensibly (documented), and label matching is correct and bounded in cost.",
        ),
    },
    {
        "name": "Ingest Throughput and Concurrency Safety",
        "weight": 6,
        "description": _band(
            "High-rate ingest is fast and safe against concurrent rollup/eviction.",
            "Each write takes a global lock and does heavy work inline; throughput collapses, or ingest races with eviction and crashes.",
            "Reasonable single-thread throughput, but ingest and background rollup/eviction can race producing torn aggregates.",
            "Hot-path writes are O(1) into the current bucket; rollup/eviction run without tearing aggregates seen by readers.",
            "Above + a benchmark reports sustained throughput and the synchronization strategy (per-series locks, sharding, or single-writer) is justified.",
        ),
    },
    {
        "name": "Code Structure and Benchmark Honesty",
        "weight": 4,
        "description": _band(
            "Levels, eviction, and query are cleanly separated and the benchmark measures what it claims.",
            "One blob mixes ingest, rollup, and query; the benchmark only times an empty loop.",
            "Reasonable separation but the benchmark ignores out-of-order/late points and reports best-case numbers only.",
            "Clear separation of ingest / rollup / retention / query; benchmark includes out-of-order points and reports throughput and steady memory.",
            "Above + the benchmark is reproducible and the candidate states the bound and the conditions under which it holds.",
        ),
    },
]


# =========================================================================
# HARD — Search / Information-Retrieval Engineer
# =========================================================================

SEARCH_PROBLEM = """\
# Inverted-Index Search with Ranking

Build **Lexicon**, a from-scratch full-text search engine over a document
corpus: tokenize and index documents, answer boolean *and* ranked queries
(TF-IDF or BM25), tolerate typos, and keep the index consistent as documents
are added, updated, and deleted. You are starting from an empty directory;
pick your language and scaffold everything yourself. Do **not** use an existing
search library (Lucene/Elasticsearch/whoosh/Tantivy) — build the index.

As part of your work, **generate a corpus yourself**: at least ~1,000 short
documents (you may synthesize them) so ranking and latency are observable.

## What to build

1. **Indexing.** `index(doc_id, text)` tokenizes (lowercase, fold, split,
   optional stemming/stop-words — your choice, justified) and builds an
   **inverted index**: term → postings (doc ids + per-doc term frequency, and
   positions if you support phrase queries). Maintain document length and the
   collection statistics ranking needs.
2. **Update / delete.** `update(doc_id, text)` and `delete(doc_id)` keep the
   index consistent — a stale term must not still point at a doc that no longer
   contains it, and collection stats (df, avgdl, N) must stay correct after
   churn.
3. **Boolean queries.** `AND`, `OR`, `NOT` over terms returning the exact
   matching set, evaluated efficiently (e.g., postings intersection, not a full
   scan).
4. **Ranked queries.** `search(query, k) -> top-k (doc_id, score)` ranked by
   TF-IDF or BM25. Scoring must be correct: idf uses live collection stats,
   length normalization is applied, and results are deterministically ordered
   (stable tie-break).
5. **Typo tolerance.** A query term within edit-distance 1 (or 2) of an indexed
   term still matches, without scanning every term in the vocabulary
   (e.g., n-gram candidate generation, a BK-tree, or a trie) — naive
   all-pairs edit distance over the whole vocabulary is not acceptable at scale.
6. **A harness** you write that builds the corpus, runs representative queries,
   and reports top-k results and query latency.

## What we care about (senior signal)

- **Ranking correctness.** Scores follow the chosen model (BM25/TF-IDF) using
  *current* collection statistics; a more relevant document outranks a less
  relevant one for sensible reasons (term frequency, rarity, length norm), and
  ties break deterministically.
- **Index update consistency.** After a mix of adds/updates/deletes, a query
  returns exactly the docs that currently contain the terms, with scores
  computed from up-to-date df/avgdl/N — no ghost postings, no stale stats.
- **Latency under many docs.** Boolean and ranked queries stay fast as the
  corpus grows (postings intersection / top-k heap), not linear scans of the
  corpus per query, and typo lookup is candidate-generated, not all-pairs.

## What we will do to it

We will index the corpus, run boolean queries and check the exact result set;
run ranked queries and verify a hand-reasoned document ranks where expected and
ties are stable; delete and re-index documents, then confirm scores and result
sets reflect the new collection stats (not the old ones); issue a misspelled
query term and confirm it still matches; and time queries on the full corpus to
confirm sub-linear behavior.

## Out of scope

- Distributed sharding / replication of the index.
- A query parser beyond simple boolean + terms (no nested grouping required,
  though it's welcome).
- Persistence to disk (in-memory index is fine; design as if it could be
  flushed).
- A UI or HTTP layer (a library API or thin CLI is enough).
"""

RUBRIC_SEARCH = [
    {
        "name": "Ranking Correctness",
        "weight": 10,
        "description": _band(
            "Scores follow the chosen model using live collection stats, with deterministic tie-breaks.",
            "Ranking is by raw term count or arbitrary order; idf/length-norm absent.",
            "TF-IDF/BM25 attempted but a component is wrong (e.g., idf not log-scaled, no length normalization) or ties order nondeterministically.",
            "Correct BM25/TF-IDF: idf from live df/N, tf saturation + length norm (BM25), top-k with a stable tie-break.",
            "Above + BM25 k1/b parameters explicit and justified, and a hand-reasoned relevant doc demonstrably outranks a less relevant one for the right reasons.",
        ),
    },
    {
        "name": "Index Update and Delete Consistency",
        "weight": 9,
        "description": _band(
            "After churn, queries return exactly current docs with up-to-date collection stats.",
            "Update/delete leaves ghost postings; deleted docs still match queries.",
            "Postings updated on delete but collection stats (df, avgdl, N) go stale, so scores after churn are wrong.",
            "update()/delete() remove stale postings and keep df/avgdl/N correct; re-indexing a doc replaces its postings atomically.",
            "Above + verified by a churn test where post-deletion scores match a freshly rebuilt index over the surviving docs.",
        ),
    },
    {
        "name": "Inverted Index and Query Efficiency",
        "weight": 9,
        "description": _band(
            "Boolean and ranked queries use the index, not corpus scans, and stay fast as the corpus grows.",
            "Every query scans all documents and re-tokenizes them; cost is O(corpus) per query.",
            "An inverted index exists but boolean ops materialize full lists then filter, or ranking scores every doc rather than only those in the postings.",
            "Postings intersection/union for boolean; ranked search touches only docs in matching postings and keeps a top-k heap.",
            "Above + postings are ordered for efficient skipping/merging and measured query latency is clearly sub-linear in corpus size.",
        ),
    },
    {
        "name": "Typo Tolerance Without All-Pairs",
        "weight": 8,
        "description": _band(
            "Near-miss query terms match via candidate generation, not whole-vocabulary edit distance.",
            "No typo tolerance, or it compares the query against every vocabulary term (all-pairs).",
            "Edit-distance matching works but scans the entire vocabulary per query term, so it does not scale.",
            "Candidate generation (n-grams / BK-tree / trie / deletion-neighborhoods) narrows the vocabulary before edit-distance scoring.",
            "Above + matched typo terms are scored sensibly (down-weighted vs. exact), and the structure's size/lookup cost trade-off is stated.",
        ),
    },
    {
        "name": "Tokenization and Analysis Soundness",
        "weight": 6,
        "description": _band(
            "Indexing and query analysis are consistent and the choices are deliberate.",
            "Naive whitespace split with no normalization; query and index analyzers differ so obvious matches miss.",
            "Lowercasing/splitting applied but inconsistently between index and query time, causing avoidable misses.",
            "Same analyzer (case-folding, tokenization, optional stemming/stop-words) at index and query time, applied consistently.",
            "Above + analysis choices (stemming, stop-words, folding) are justified for the corpus and their effect on recall/precision is acknowledged.",
        ),
    },
    {
        "name": "Boolean Query Correctness",
        "weight": 6,
        "description": _band(
            "AND/OR/NOT return the exact correct matching set.",
            "Boolean operators produce wrong sets (e.g., NOT returns everything, AND behaves like OR).",
            "AND/OR correct but NOT is mishandled (no universe to subtract from) or operator precedence is undefined.",
            "AND/OR/NOT return exact sets with defined precedence/evaluation order; verified against brute-force set computation.",
            "Above + NOT is bounded (subtracts from the live doc set, not an infinite universe) and combined boolean+ranked behavior is well-defined.",
        ),
    },
    {
        "name": "Code Structure and Benchmark Honesty",
        "weight": 5,
        "description": _band(
            "Analyzer, index, and ranker are separable and the benchmark reflects real query cost.",
            "One file mixes tokenizing, indexing, and scoring; the benchmark times indexing only, not queries.",
            "Reasonable separation but the latency benchmark uses a trivial corpus that hides scaling behavior.",
            "Analyzer / inverted index / ranker / typo-index cleanly separated; benchmark runs representative queries on the ~1k-doc corpus and reports latency.",
            "Above + benchmark is reproducible and reports both indexing throughput and query latency as the corpus grows.",
        ),
    },
]


# =========================================================================
# HARD — Platform / Backend Engineer (rate limiting)
# =========================================================================

RATELIMIT_PROBLEM = """\
# Multi-Tenant Rate Limiter / Quota Service

Build **Throttle**, a multi-tenant rate-limiting and quota service. Many
tenants share the service; each tenant has per-route limits and a longer-window
quota. The limiter must be **accurate at the window boundary**, **race-safe**
under concurrency, and must never let one tenant's traffic affect another's.
You are starting from an empty directory; pick your language and scaffold
everything yourself.

## What to build

1. **Limit configuration** per `(tenant, route)`: a sliding-window rate limit
   (e.g., 100 requests / 60s) and a longer **quota window** (e.g.,
   10,000 requests / day). Limits are configurable in a file/store you control.
2. **`check(tenant, route, now) -> {allowed, limit, remaining, reset_after,
   retry_after}`** — the decision a gateway would make per request. Allowed
   requests count against both the rate limit and the quota; denied requests do
   not consume quota.
3. **Sliding window, not fixed buckets.** A naive fixed-window counter lets
   ~2× the limit through across a boundary (e.g., a burst at 0:59 and another
   at 1:01). Implement a real sliding window — sliding log or sliding-window
   counter (weighted previous + current bucket) — and document which.
4. **Burst handling.** Optionally support a token-bucket-style burst allowance
   on top of the sustained rate (e.g., burst of 20 above 100/60s). If you
   support it, the sustained rate must still be enforced over time.
5. **Tenant isolation + fairness.** One tenant hammering a route must not
   exhaust shared structures or starve another tenant; per-tenant state is
   isolated, and memory does not grow unboundedly with idle tenants
   (expiry/eviction of cold keys).
6. **Race safety.** Concurrent `check()` calls for the same key must not admit
   more than the limit; the count-and-decide step is atomic. Build a harness
   that fires concurrent requests and asserts the admitted count never exceeds
   the limit.

## What we care about (senior signal)

- **Boundary accuracy.** Across the window boundary the limiter admits at most
  the configured rate — no 2× leakage that a fixed-window counter allows.
- **No cross-tenant leakage.** Tenant A's usage, denials, and remaining quota
  are completely independent of tenant B's; keys are namespaced so one tenant
  cannot read, affect, or evict another's counters.
- **Race safety.** Under N concurrent requests against a key with limit L, at
  most L are admitted — never L + (concurrency races). The atomic step is
  identifiable in the code.

## What we will do to it

We will send a burst at the end of one window and another at the start of the
next and confirm the sliding window does not admit ~2× the rate; fire many
concurrent requests at a single key and assert admitted ≤ limit exactly;
exhaust a tenant's quota and confirm denied requests return `retry_after` and
do not decrement quota further; drive heavy traffic for one tenant and confirm
another tenant's limits are unaffected; and let many tenants go idle to confirm
cold-key memory is reclaimed.

## Out of scope

- A distributed/multi-node limiter with shared Redis — single-process is fine,
  but design the atomic step as if it could move to a Lua/CAS primitive.
- Authentication of the caller (trust the `tenant` argument).
- A UI; a library API or thin HTTP layer is enough.
- Persisting counters across restarts.
"""

RUBRIC_RATELIMIT = [
    {
        "name": "Window-Boundary Accuracy",
        "weight": 10,
        "description": _band(
            "Across the window boundary, admitted requests never exceed the configured rate.",
            "Fixed-window counter that resets at the boundary, allowing ~2× the limit across it.",
            "Attempts a sliding window but the boundary math is off (e.g., previous window not weighted), still leaking above the limit near the edge.",
            "Real sliding window (sliding log or weighted sliding-counter) that admits at most the rate across a boundary; the algorithm is documented.",
            "Above + the boundary burst test (burst at 0:59 + 1:01) admits ≤ limit over any 60s span, and the weighting math is shown correct.",
        ),
    },
    {
        "name": "Concurrency / Race Safety",
        "weight": 10,
        "description": _band(
            "Concurrent checks on one key admit at most the limit; the decide step is atomic.",
            "check() reads the count then increments separately, so concurrent requests over-admit (L + races).",
            "Some locking but it wraps too little (read and write not in one critical section) so a race window remains.",
            "Count-and-decide is atomic per key (lock or CAS); under concurrency admitted ≤ limit exactly.",
            "Above + a concurrency stress test proves admitted == limit (not more) under heavy contention, and the atomic step is clearly identifiable / portable to a CAS primitive.",
        ),
    },
    {
        "name": "Tenant Isolation and Namespacing",
        "weight": 9,
        "description": _band(
            "One tenant's traffic, counters, and eviction never affect another tenant.",
            "Counters keyed by route only, so tenants share buckets and leak into each other.",
            "Keyed by (tenant, route) for counting but a shared structure (global lock or shared eviction) lets one tenant starve another.",
            "Per-(tenant, route) namespaced state; one tenant's load does not change another's decisions; isolation tested explicitly.",
            "Above + a hot tenant cannot exhaust shared capacity or evict another tenant's keys; fairness is demonstrated under skewed load.",
        ),
    },
    {
        "name": "Quota Window and Denial Semantics",
        "weight": 8,
        "description": _band(
            "The longer quota window is enforced correctly and denied requests don't consume quota.",
            "No separate quota, or denied requests still decrement remaining quota.",
            "Quota tracked but its window handling is naive (fixed daily reset with the same boundary leakage) or denials are miscounted.",
            "Rate limit and quota both enforced; allowed requests count against both, denials consume neither; remaining/reset surfaced correctly.",
            "Above + retry_after / reset_after are accurate to the windowing model, and the rate-vs-quota interaction (which denies first, what the caller sees) is documented.",
        ),
    },
    {
        "name": "Burst Handling Correctness",
        "weight": 7,
        "description": _band(
            "Burst allowance is bounded and the sustained rate still holds over time.",
            "Burst is unbounded (effectively no limit during a burst) or sustained rate is abandoned once burst is enabled.",
            "Token-bucket-ish burst but refill math is wrong, so sustained throughput drifts above or below the configured rate.",
            "Burst allowance is capped and refills correctly; sustained rate is enforced over a longer horizon even with bursts.",
            "Above + the burst-vs-sustained model is documented, and a test shows a burst is absorbed once but sustained traffic settles to the configured rate.",
        ),
    },
    {
        "name": "Cold-Key Eviction and Bounded Memory",
        "weight": 6,
        "description": _band(
            "Idle tenant/route keys are reclaimed so memory does not grow without bound.",
            "Every key ever seen is retained forever; memory grows with total distinct keys.",
            "Eviction exists but is unsafe (can drop a key with an in-flight window, briefly resetting a live limit).",
            "Cold keys expire after their window elapses; eviction never resets an active limiter or loses an in-window count.",
            "Above + memory is bounded by active-key count and the eviction policy is tested under a flood of one-shot tenants.",
        ),
    },
    {
        "name": "Decision Contract and Observability",
        "weight": 5,
        "description": _band(
            "The check() response is a complete, accurate, gateway-usable contract.",
            "Returns only a boolean; no remaining/reset/retry information.",
            "Returns allowed + remaining but reset_after/retry_after are missing or wrong relative to the algorithm.",
            "Returns allowed, limit, remaining, reset_after, retry_after consistent with the windowing model; per-tenant metrics available.",
            "Above + values are accurate at the boundary and under bursts, and denials are observable (per-tenant denial counters) for capacity planning.",
        ),
    },
]


# =========================================================================
# HARD — Platform / Infra Engineer (orchestrator)
# =========================================================================

ORCHESTRATOR_PROBLEM = """\
# Process / Task Orchestrator-Lite

Build **Conductor**, a task orchestrator that runs a DAG of tasks with
dependency ordering, a global concurrency limit, health checks, and
restart-with-backoff on failure. You are starting from an empty directory; pick
your language and scaffold everything yourself. Tasks are in-process (a function
/ command you simulate), so the whole thing runs deterministically in a test.

## What to build

1. **DAG definition.** Tasks declare dependencies: `add_task(id, run, deps=[...
   ], retries, backoff, health_check=None)`. The orchestrator builds the
   dependency graph and **detects cycles** (refuses to run a cyclic graph with
   a clear error).
2. **Dependency-respecting scheduling.** A task starts only after **all** its
   dependencies have completed successfully. Independent tasks may run in
   parallel up to a configurable **global concurrency limit**. A failed task
   that exhausts its retries fails its downstream dependents (they do not run)
   while unrelated branches continue.
3. **Restart-with-backoff.** A task that fails is retried up to `retries` times
   with **exponential backoff** (base × 2^attempt, with optional jitter and a
   max cap). The backoff math must be correct and bounded; document the formula.
4. **No thundering herd.** When many tasks become eligible at once (a fan-out,
   or many retries firing together), they must not all launch in the same
   instant and overwhelm the concurrency limit or a shared downstream — jitter
   and the concurrency cap must smooth the launch.
5. **Health checks.** A long-running task may expose a health check; if it goes
   unhealthy, the orchestrator treats it as failed and applies the
   restart/backoff policy. Define liveness vs. a one-shot completion clearly.
6. **Deterministic clock + harness.** Use an injectable clock so backoff and
   timeouts are testable without real sleeps. Build a harness that runs DAGs
   under injected failures and asserts ordering, concurrency, and backoff.

## What we care about (senior signal)

- **DAG correctness.** A task never starts before every dependency has
  *succeeded*; a dependency failure correctly blocks its dependents while
  unrelated branches proceed; cycles are rejected up front.
- **Backoff math.** Retry delays follow the documented exponential formula,
  are capped, and (with jitter) do not all fire simultaneously; total attempts
  equal `retries + 1`, not off-by-one.
- **No thundering herd.** A fan-out of N newly-eligible tasks, or N retries
  coming due together, is smoothed by the concurrency limit and jitter rather
  than spiking to N concurrent launches.

## What we will do to it

We will define a diamond DAG (A → B, A → C, B+C → D) and assert D runs only
after B and C succeed and that B and C ran concurrently; fail a task and assert
it retries exactly `retries` times with delays matching the backoff formula on
the injected clock; fail a mid-graph task permanently and confirm its
dependents are skipped while a parallel branch completes; submit a cyclic graph
and confirm it is rejected; and fan out 50 tasks with a concurrency limit of 5
and assert at most 5 ever run at once.

## Out of scope

- A real process supervisor / OS process spawning — simulated in-process tasks
  are fine (but model task failure, timeout, and health realistically).
- Distributed scheduling across machines.
- Persisting DAG state across restarts (in-memory is fine; design as if it
  could be persisted).
- A UI; a library API plus a status dump is enough.
"""

RUBRIC_ORCHESTRATOR = [
    {
        "name": "DAG Ordering Correctness",
        "weight": 10,
        "description": _band(
            "A task starts only after every dependency has succeeded; failures block dependents, unrelated branches proceed.",
            "Tasks run in submission order ignoring deps, so a task can start before its dependency finishes.",
            "Deps respected on the happy path, but a dependency *failure* still lets dependents run, or it blocks unrelated branches too.",
            "A task waits for all deps to succeed; a failed dep skips its dependents while independent branches continue.",
            "Above + verified on the diamond DAG (D waits for B and C, B and C run in parallel) and a permanent mid-graph failure skips exactly the downstream set, nothing more.",
        ),
    },
    {
        "name": "Cycle Detection",
        "weight": 7,
        "description": _band(
            "A cyclic graph is detected and rejected before execution with a clear error.",
            "A cyclic graph deadlocks or infinite-loops at runtime.",
            "Cycles are caught only by hitting a recursion/visit limit at runtime, not validated up front.",
            "Cycle detection (topological check / DFS) runs before execution and rejects the graph naming the cycle.",
            "Above + self-dependencies and references to unknown task ids are also rejected with clear, specific errors.",
        ),
    },
    {
        "name": "Backoff Math Correctness",
        "weight": 9,
        "description": _band(
            "Retry delays follow the documented exponential formula, are capped, and attempt counts are exact.",
            "No backoff (immediate retry) or a fixed delay regardless of attempt; or off-by-one so it retries the wrong number of times.",
            "Exponential growth but uncapped (delays explode) or the attempt count is off-by-one (retries+1 confusion).",
            "Delay = base × 2^attempt capped at a max; total attempts == retries + 1; formula documented.",
            "Above + jitter is applied within documented bounds and the on-clock test confirms each retry fires at the expected (jittered) time.",
        ),
    },
    {
        "name": "Concurrency Limit Enforcement",
        "weight": 9,
        "description": _band(
            "Never more than the configured number of tasks run at once, even under fan-out.",
            "All eligible tasks launch immediately; the concurrency limit is ignored.",
            "Limit mostly respected but a burst of newly-eligible tasks can momentarily exceed it due to a check-then-launch race.",
            "A counting semaphore / worker pool caps in-flight tasks at the limit; eligible tasks queue when the pool is full.",
            "Above + the 50-task fan-out with limit 5 is shown to never exceed 5 concurrent, and the cap holds atomically under the scheduler's concurrency.",
        ),
    },
    {
        "name": "Thundering-Herd Avoidance",
        "weight": 8,
        "description": _band(
            "Mass-eligible tasks and simultaneous retries are smoothed, not spiked.",
            "A fan-out or a wave of retries all launch in the same instant, spiking far past the concurrency limit's intent.",
            "Concurrency cap prevents over-launch but all retries come due at the exact same tick (no jitter), creating synchronized waves.",
            "Jitter spreads retry/launch times and the concurrency cap throttles fan-out so launches are staggered.",
            "Above + demonstrated: N synchronized retries do not all fire on the same tick, and downstream launch rate stays bounded.",
        ),
    },
    {
        "name": "Health Check and Failure Semantics",
        "weight": 7,
        "description": _band(
            "Liveness vs. completion is well-defined; an unhealthy task is failed and retried per policy.",
            "No health-check concept; a hung task hangs the orchestrator forever.",
            "Health checks exist but a failing one is not wired into the retry/backoff path, or a task that completes is still polled as if live.",
            "One-shot completion and liveness are distinct; an unhealthy long-running task is marked failed and goes through restart/backoff; timeouts bound a hung task.",
            "Above + repeated unhealthiness eventually exhausts retries and fails dependents cleanly, and the distinction is documented.",
        ),
    },
    {
        "name": "Deterministic Clock and Harness",
        "weight": 6,
        "description": _band(
            "Backoff and timeouts run on an injectable clock; tests are deterministic without real sleeps.",
            "Real time.sleep() drives backoff; tests are slow and flaky.",
            "A clock abstraction exists but some paths still use wall-clock, so timing tests remain racy.",
            "All delays/timeouts go through an injected clock; advancing it deterministically drives retries and timeouts.",
            "Above + the harness asserts ordering, concurrency ceiling, and exact backoff timing on the simulated clock with reproducible runs.",
        ),
    },
    {
        "name": "Code Structure and Status Observability",
        "weight": 5,
        "description": _band(
            "Scheduler, task state machine, and policy are separated and run status is inspectable.",
            "One loop mixes scheduling, retry policy, and task execution; no way to see task states.",
            "Reasonable separation but task state (pending/running/succeeded/failed/skipped) is implicit and not queryable.",
            "Clear task state machine and a status dump showing each task's state, attempts, and next-retry time.",
            "Above + the policy (retries/backoff/concurrency) is configurable and isolated from the scheduler core, so a reader can swap it without rewriting scheduling.",
        ),
    },
]


# =========================================================================
# Challenge library catalogue
# =========================================================================

CHALLENGE_LIBRARY: list[dict] = [
    {
        "title": "Raft-Lite Log Replication",
        "slug": "raft-lite-log-replication",
        "description": (
            "Distributed Systems interview. Build a Raft-style replicated log on a "
            "simulated cluster with injectable partitions: leader election, "
            "append-entries replication, and a commit index that is safe under "
            "partition. Senior signal: no committed-entry loss, correct term/leader "
            "rules, deterministic safety under fuzzing."
        ),
        "category": "distributed",
        "difficulty": "hard",
        "time_limit_minutes": 150,
        "rubric": RUBRIC_RAFT,
        "max_budget_usd": 12.0,
    },
    {
        "title": "CRDT Collaborative Text Buffer",
        "slug": "crdt-collaborative-text-buffer",
        "description": (
            "Real-Time Collaboration interview. Build a conflict-free replicated text "
            "buffer (RGA/LSEQ-style) where concurrent inserts and deletes converge "
            "across replicas with no central server. Senior signal: convergence under "
            "reordering/duplication, intention preservation, and disciplined tombstone "
            "handling."
        ),
        "category": "realtime",
        "difficulty": "hard",
        "time_limit_minutes": 135,
        "rubric": RUBRIC_CRDT,
        "max_budget_usd": 11.0,
    },
    {
        "title": "Time-Series Metrics Store",
        "slug": "time-series-metrics-store",
        "description": (
            "Data / Observability interview. Build an embeddable metrics store that "
            "ingests high-rate points, downsamples into rollups, enforces retention, "
            "and answers range queries under a bounded memory budget. Senior signal: "
            "bounded memory, correct aggregation across rollup boundaries, and a clear "
            "late-arriving-point policy."
        ),
        "category": "data",
        "difficulty": "hard",
        "time_limit_minutes": 120,
        "rubric": RUBRIC_TSDB,
        "max_budget_usd": 10.0,
    },
    {
        "title": "Inverted-Index Search with Ranking",
        "slug": "inverted-index-search-with-ranking",
        "description": (
            "Search / Information-Retrieval interview. Build a from-scratch full-text "
            "engine: inverted index, boolean and ranked (TF-IDF/BM25) queries, and "
            "typo tolerance, kept consistent as documents churn. Senior signal: ranking "
            "correctness on live stats, index-update consistency, and sub-linear query "
            "latency."
        ),
        "category": "search",
        "difficulty": "hard",
        "time_limit_minutes": 120,
        "rubric": RUBRIC_SEARCH,
        "max_budget_usd": 10.0,
    },
    {
        "title": "Multi-Tenant Rate Limiter / Quota Service",
        "slug": "multi-tenant-rate-limiter-quota-service",
        "description": (
            "Platform / Backend interview. Build a multi-tenant rate limiter with "
            "per-(tenant, route) sliding-window limits, burst handling, and longer-window "
            "quotas. Senior signal: accuracy at the window boundary, no cross-tenant "
            "leakage, and race safety so admitted requests never exceed the limit under "
            "concurrency."
        ),
        "category": "platform",
        "difficulty": "hard",
        "time_limit_minutes": 110,
        "rubric": RUBRIC_RATELIMIT,
        "max_budget_usd": 9.0,
    },
    {
        "title": "Process / Task Orchestrator-Lite",
        "slug": "process-task-orchestrator-lite",
        "description": (
            "Platform / Infra interview. Build a task orchestrator that runs a DAG with "
            "dependency ordering, a global concurrency limit, health checks, and "
            "restart-with-backoff. Senior signal: DAG correctness (no task runs before "
            "its deps succeed), exact backoff math, and no thundering herd on fan-out or "
            "synchronized retries."
        ),
        "category": "backend",
        "difficulty": "hard",
        "time_limit_minutes": 120,
        "rubric": RUBRIC_ORCHESTRATOR,
        "max_budget_usd": 10.0,
    },
]
