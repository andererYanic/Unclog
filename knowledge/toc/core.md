# Theory of Constraints: core reference

Tags: `novel` = in *The Goal*; `later-TOC` = formalized in Goldratt's later books (brief §2.3).

## The goal and three measures `later-TOC` (formal definitions)
- **Throughput (T):** money generated through *sales*: revenue minus truly variable costs.
- **Inventory (I):** money tied up in things meant to be sold or that enable selling: WIP, stock,
  open orders and quotes, tools.
- **Operating expense (OE):** money spent to turn I into T: payroll, licences, inference.
- Every improvement is tested as: does T go up, I go down, or *realized* OE go down, for the
  whole system?

## Laws used in the code `novel`
| Law | Where it is enforced |
|---|---|
| An hour lost at the bottleneck is lost for the whole system | relief test, ΔT only from constraint (value model) |
| An hour saved at a non-bottleneck is a mirage | mirage ledger, NCX-10 defer, noise-tested ΔT |
| Dependent events + statistical fluctuations | discrete-event simulation with variability |
| Balance flow, not capacity | DBR rope; never recommend cutting protective capacity |
| Smaller transfer batches cut lead time and WIP | batch policies detected; exploit scenario |
| Setup at the bottleneck is lost capacity | task setup per batch in load model |
| Policies can be the constraint | policy hypotheses, policy branch in goal trees |
| After a physical constraint breaks, the market often becomes the constraint | next-constraint prediction, market hypotheses |

## Five Focusing Steps `novel`
1. **Identify** the constraint (heat table → hypotheses → confirmation tests).
2. **Exploit:** no idle time, no waste, quality in, right sequence.
3. **Subordinate** everything else to the constraint's pace.
4. **Elevate** (add capacity) only after 2 and 3 are documented.
5. **Repeat**: watch for inertia (old rules outliving the old constraint).

## Drum-Buffer-Rope `later-TOC` (named in later works; idea in the novel)
- **Drum:** the constraint sets the pace.
- **Buffer:** a time buffer in front of the drum so it never starves.
- **Rope:** release new work only at the drum's pace. Rule of thumb: WIP from release
  ≈ drum throughput × buffer time (Little's law).

## Buffer management `later-TOC`
Penetration into the time buffer: green (< ⅓ consumed), yellow (< ⅔), red (beyond).
Red items are expedited and their causes logged. That cause list is the improvement backlog
(POOGI).

## AI-specific corollaries (Unclog)
NCX-10 rule, flooding trap, review as the new constraint, expertise and decision authority as
constraints, cost-world vs throughput-world, variability reduction is capacity, inference cost
is OE, don't automate a policy constraint, don't automate a broken process. See brief §2.4.
