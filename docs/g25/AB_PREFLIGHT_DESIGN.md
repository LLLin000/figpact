# G25 A/B1 Preflight Design (DRAFT — design only)

Status: **DRAFT design document, not a freeze, not an implementation.**
No model call, no product code change, no test/build run, no commit is
authorized by this file. All G25 sample cases remain **candidate/draft only**
until an independent annotator exists and signs off; no JSON gold file may be
tagged frozen on the basis of this design. G25-0 preflight observes
`model_called=false` always.

Authoritative code baseline (only facts used by this design):

- Packet envelope: `figpact/edit_plan.py:17-33` (`SYSTEM_PROMPT`),
  `:35-51` (`PLAN_SCHEMA`), `:54-58` (`request_packet`),
  `:107-121` (`combine_contexts`).
- Native context: `figpact/plan_context.py:89-175` (`discover_native`).
- Overlay context: `figpact/plan_context.py:188-270` (`discover_overlay`),
  node projection without parent/scope at `:244-247`.
- Overlay role closed set: `figpact/style_identity.py:62-68`
  (`ALLOWED_TARGETS`); ranges `figpact/style_overlay.py:38-39`
  (`FONTSIZE_RANGE`, `LINEWIDTH_RANGE`).
- Freeze-shape constraints (schema only, not a frozen claim):
  `docs/g25/G25_0_FREEZE_SCHEMA.md` §4 (A/B packets + `ab_equivalence.json`),
  §8 (provenance tags), §9 check D1–D6.
- Protocol variable definition: `docs/G25_PROTOCOL.md` §Semantic Target Hints
  (arm A vs presentation-only arm B; information-gain is a separate arm).

Naming in this file: **A** = production baseline packet. **B1** = pure
presentation reorder of A's facts. **B2** = optional, pre-registered
information-gain arm. B2 exists only when the study pre-registers added
source fields; otherwise the round is A/B1 only.

---

## 1. What A is (exact construction)

Per sample, A MUST be built by the current production path, no shortcuts:

1. Start an **isolated fresh process** (see §7) with a **copied config** and
   a **fresh overlay file in an empty directory**. Never point preflight at
   the shipped YAML or the shared workspace overlay.
2. Call the live discovery matching the sample's single route
   (`discover_native` and/or `discover_overlay`), or `combine_contexts`
   when the context genuinely carries two routes for one scope. Single route
   + single scope per `PLAN_SCHEMA` remains the capability boundary; a
   cross-scope or dual-route atomic request is a capability-boundary sample
   (`schema_representability=UNREPRESENTABLE`), never a READY packet.
3. Wrap with `request_packet(request, context)` verbatim: `request` is the
   frozen natural-language string, unedited; `system` is `SYSTEM_PROMPT`
   bytes; `schema` is `PLAN_SCHEMA` bytes; `input.context` is the discovery
   output from step 2.
4. Record the A bytes exactly as the model would see them
   (`ab_packets/<sample_id>/A.json`). No pretty-print drift: the stored
   bytes are the hashed bytes (see §6).

A therefore already carries every production-visible fact the design must
protect: scope, revision, control list (with IDs, roles, ranges, currents),
route contexts, nodes, measurement/frame metadata, and source fingerprints.

---

## 2. Normalized fact model (equivalence dimensions)

Equivalence is computed over a **normalized fact multiset** extracted
deterministically from each arm's payload — never over raw strings, key
names, layout, or hint prose. One fact = one
`{dimension, control_ref, value, provenance}` tuple. The checker extracts
exactly these dimensions; anything else in the payload is presentation and
is ignored by the fact hash (but still stored for audit).

| # | Dimension | Native source field(s) | Overlay source field(s) | Normalization rule |
|---|---|---|---|---|
| 1 | `scope` | `context.scope`; per-control `controls[].scope` | same | verbatim string; multiset over controls + envelope |
| 2 | `panel` | scene node `id` with `type` panel/Axes + control `objects` membership | `controls[].objects` (scene ids); inventory descriptor axes membership | panel = the registered node id referenced by `objects`; ordinal `scope::panel.<index>` is kept literally and tagged `ORDINAL_FALLBACK` (never normalized into a persistent id) |
| 3 | `parent` | scene node `parent` (`plan_context.py:148-150`) | **absent by construction** (projection has no parent/scope, `:244-247`) | present only when the arm payload literally carries it; missing parent normalizes to `ABSENT`, never inferred from geometry |
| 4 | `role` | `controls[].role` (= `expected.kind` or `operation`, verbatim copy) | `controls[].role` restricted to `axis.title \| axis.tick \| curve.linewidth` closed set | verbatim string; unknown/empty normalizes to `UNKNOWN` and MUST be omitted from B1 hints (§8 rule 3) |
| 5 | `axis` | `controls[].axis` (`x \| y \| null`) | descriptor `axis` via `controls[].role` + selector context | `x`/`y` only when the source field says so; ordinal `axes_index` never normalizes to `axis` |
| 6 | `ID` (control identity) | `controls[].id` = compact-JSON path (`json.dumps(path)`); `key` is display only | `controls[].id` = `target_id` | verbatim string; the **canonical control-ID set** (§6); `key`/`label`/`display` text never enters the ID set |
| 7 | `path` | `controls[].path` (exact YAML segment list) | `null` (Overlay has `path: null` by model, `:222`) | segment list joined with `/` for hashing; Overlay path fact is explicit `ABSENT`, not an empty path |
| 8 | `current` | `controls[].current` + `current_unresolved` + `value_shape` | `controls[].current_pt` as `current`, `saved_pt` as `saved`, `value_shape=scalar` | `_clean` output as-is (non-finite → `None`); unresolved stays a fact (`current_unresolved=true`), never replaced by a guess |
| 9 | `range` | `controls[].min/max/scale` | `min/max` from `FONTSIZE_RANGE`/`LINEWIDTH_RANGE` by property | numeric pair as JSON numbers; missing bound = `None`, never default-filled |
| 10 | `unit` | `controls[].unit` | literal `"pt"` | verbatim string |
| 11 | `selector` | `ABSENT` (Native binds by `path`, not selector) | `controls[].selector` (opaque descriptor string) | verbatim string; Native selector fact is explicit `ABSENT` |
| 12 | `objects` | `controls[].objects` (contract-declared object list) | `controls[].objects` (`scene_ids`) | sorted string list per control; empty = `[]`, never `null`-coalesced |
| 13 | `provenance` | per §8 tag on every identity assertion | per §8 tag on every identity assertion | enum + `{derivation, authoritative, persistent}` verbatim (see §5) |

Extraction inputs are the **stored arm bytes only**. The extractor MUST NOT
read the gold file, the live session a second time, or any sidecar note.
Source revisions and overlay path identity (§7) are recorded alongside the
packet for audit but are **not** facts: two arms share one sample revision,
so revision fields are asserted equal by string comparison, not hashed into
the fact set.

---

## 3. B1 construction (presentation-only; the strict arm)

B1 starts as a byte copy of A's discovery output, then applies **only**
allowable transformations:

**Allowed (exhaustive):**

- Rename packet keys, regroup JSON nesting, reword hint prose, change hint
  ordering **within one object's hint block**.
- Emit read-only per-object hint blocks that collocate facts already present
  in A for the same control: its scope, panel/node id, role, axis, ID/path,
  current, range, unit, selector, objects — each hint annotated with
  `{text, source_field, derivation_rule, provenance}`.
- Drop nothing silently: every A fact MUST appear in B1's fact multiset
  (see omission rule below for structurally absent fields).

**Forbidden (any one fails the arm):**

- Add, remove, or reword any fact value (IDs, paths, roles, axes, currents,
  ranges, units, selectors, object lists, scope strings, revision strings).
- Fill a structurally absent field. Concretely: B1 MUST NOT invent Overlay
  `parent`/`scope-per-node`, MUST NOT promote `axes_index` to `axis`, MUST
  NOT promote bbox proximity to `anchored_to`, MUST NOT promote `label`/
  `display` text to a control ID, MUST NOT resolve `UNKNOWN` role/axis into
  a guessed value.
- Reorder, rank, emphasize, or de-emphasize controls as answer cues: the
  control array order in **both** arms MUST be the same canonical sort
  (by `id`, bytewise) before hashing and before display, so hint grouping
  carries no priority signal. Hint blocks MUST NOT contain ordinal language
  ("first", "best match", "likely target"), MUST NOT single out the gold
  target, and MUST NOT echo request-specific values back as suggestions.
- Copy any value from the request string into a hint as if it were a
  measured current/range (request text is untrusted input, not a fact).

**Symmetric-omission rule (the Overlay-completeness case):**
When a dimension is structurally absent in one route's discovery model, B1
handles it by **omitting that dimension's hints from both arms' hint layer
for the affected controls** — never by backfilling. Example: Overlay nodes
carry no `parent`/`scope`, so B1 emits no parent/scope hints for Overlay
controls **and** strips (or, if A has no hint layer, simply adds no)
parent/scope hints for Native controls in the compared hint view either;
the underlying Native `parent` facts remain in both arms' fact multisets
because they were in A. What is forbidden is manufacturing the missing
side's facts to "match". If a study wants those manufactured fields, that
is B2, not B1 (§4).

Each B1 hint records its lineage so an auditor can replay it without the
gold file:

```text
hint = {text, source_field, derivation_rule, provenance}
# source_field:  "context.controls[3].role" (JSON-pointer style, arm-relative)
# derivation_rule: one of VERBATIM | REGROUP_BY_OBJECT | OMIT_ABSENT | CANONICAL_SORT
# provenance:      §8 tag object {source, derivation, authoritative, persistent}
```

`derivation_rule` is closed: any hint whose rule is not one of the four
above fails equivalence.

---

## 4. B2 (optional information-gain arm; never merged into B1)

B2 exists **only** when pre-registered as a separate study arm with named
added fields. It is built from A plus an explicit additive transform, and
it gets **no equivalence assertion** — instead an additive disclosure:

- Per added field: `{field, source, derivation, unknown_rate}` where
  `source` names the real origin (e.g. re-resolved `OVERLAY_INVENTORY`
  descriptor `axes_key`, registry GID lookup, contract relation id),
  `derivation` is the exact construction rule, and `unknown_rate` is the
  fraction of controls/samples where the field was `UNKNOWN`/omitted.
- B2 MUST NOT be averaged with B1 or described as "presentation
  improvement". Its analysis compares A-vs-B2 (information effect)
  separately from A-vs-B1 (presentation effect).
- If the resource (unseen samples, annotator time) does not support a third
  arm, the round stays A/B1 and B2 is recorded as absent — not as
  zero-effect.

---

## 5. Why Overlay context completeness differs (and what follows)

Native discovery (`discover_native`) returns a scene projection with
`id/type/parent/scope/bounds_mm` per node plus per-control `path/role/
objects/scope/axis/current` — the packet already carries parentage and
scope membership as first-class facts.

Overlay discovery (`discover_overlay`) deliberately projects less: nodes
carry only `id/type/bounds_mm` (`plan_context.py:244-247`); authority lives
in the inventory descriptors (`id/role/property/scope/selector/
fingerprint/current/unique/eligible`), joined onto `style.targets`
(`target_id/property/current_pt/saved_pt/scene_ids/label/display`). There
is no `parent`, no per-node `scope`, no `path`; `axes_index` is a display
hint, not authority (`style_identity.py` identity rules); spatial
proximity/above-below language is a render observation, never a binding
basis (protocol §来源约束与可行性 + freeze-schema §8 rules 4–6).

Consequences for the design:

1. B1 can only collocate what A already has per arm. For Overlay controls
   that means: id, role (closed set), property, axis (when the descriptor
   states it), current/saved, range, unit `pt`, selector, objects, scope
   (envelope-level), display/label as **non-authoritative** text.
2. Any B1 hint that states an Overlay control's parent, per-node scope,
   anchor, or persistent panel identity beyond `objects`+descriptor is a
   **new fact** and reroutes that sample to B2 handling.
3. Provenance tags make the asymmetry explicit instead of papering over it:
   Overlay spatial hints are `RENDER_OBSERVATION, authoritative:false,
   persistent:false`; ordinal panels are `ORDINAL_FALLBACK,
   persistent:false`; unprovable assertions are `UNKNOWN` and omitted.

---

## 6. Proving equality (canonicalization + checker, no answer leakage)

**Canonicalization (both arms, identical function):**

1. Parse stored arm bytes as JSON. Extract the fact multiset per §2.
2. Sort facts by `(dimension, control_ref, value-canonical)` bytewise;
   sort `objects` lists and the control-ID set bytewise. Control display
   order is re-sorted by `id` bytewise — original order is not a fact.
3. Serialize with the G24-descended canonical form: `sort_keys=True,
   ensure_ascii=False, allow_nan=False`, UTF-8, SHA256
   (`tools/g24/score.py:39-41`口径; freeze-schema §5). One hash covers the
   fact multiset (`fact_set_sha256`); a second covers the sorted control-ID
   list (`control_ids_sha256`).

**Checker output** (`ab_equivalence.json`, one record per sample; shape
follows freeze-schema §4, D3):

```text
{sample_id, arm_pair: "A-vs-B1",
 control_ids_equal: bool, fact_set_equal: bool,
 only_presentational_diff: bool, pass: bool,
 detail: {a_fact_sha, b_fact_sha, a_ids_sha, b_ids_sha,
          missing_in_B: [...], extra_in_B: [...],
          value_mismatches: [...], hint_lineage_gaps: [...]}}
```

`pass` requires all three booleans true. Any `missing_in_B`, `extra_in_B`,
or `value_mismatches` entry fails the sample; any hint lacking
`{text, source_field, derivation_rule, provenance}` or using a
non-closed derivation rule fails via `hint_lineage_gaps`. B1 samples with
`pass=false` are excluded from every "presentation effect" denominator
(D3) but remain in the freeze as evidence.

**No-leakage construction:**

- The extractor + checker inputs are **only** the two stored arm payloads
  for that sample. They never read `cases_gold.json`, expected
  target/binding/value, preflight feasibility receipts beyond the shared
  revision strings, other samples' packets, or any model output.
- Equivalence runs **before** gold binding/value adjudication and does not
  take the request semantics as input beyond the verbatim request string
  already inside both packets.
- `detail` reports dimension/control_ref/value triples that differ — never
  the gold answer, never a suggested control. An auditor replaying the
  checker learns whether the arms match, not which control is correct.

---

## 7. Freshness, identity, tokens, and `model_called=false`

- **Independent fresh processes:** one process per (sample, arm). Each
  process builds its discovery output from the isolated copy, writes its
  arm packet, and exits. No shared worker state, no reused session, no
  cross-arm caching. A and B1 for the same sample share input **bytes**
  (same copied config + same overlay file + same script revision) but never
  a live session object.
- **Source/overlay identity (recorded per sample, asserted equal across
  arms):** script bytes SHA256, config bytes SHA256, `contract_source`,
  `base_config_revision`, `source_revision` (Native) or script/config/
  overlay path + `overlay_sha256` + dependency `{name: [path, digest]}`
  map + `frame_revision` (Overlay). Any cross-arm mismatch in these strings
  fails the sample before fact comparison — it means the arms were not
  built from the same live state.
- **Token/truncation logging:** per arm record `{tokenizer, token_count,
  truncated: bool, truncation_rule, kept_prefix_bytes}`. If the serving
  stack truncates packets, the truncation rule MUST be fixed in advance,
  applied identically to both arms, and logged; any run where truncation
  removes facts from one arm but not the other fails equivalence (the
  surviving fact multisets, post-truncation, are what get hashed — and the
  failure detail shows exactly which facts were lost). No silent
  summarization, no arm-specific compression.
- **Preflight never calls the model under test:** every preflight evidence
  record carries `model_called: false` with `isolated_copy: true`,
  `receipt_raw` preserved verbatim (engine/science/view/QA state), and the
  config+overlay+script SHAs above. Trialing a candidate plan through the
  existing engine (`validate_candidate`) is preflight's only execution, and
  it runs on the isolated copy.

---

## 8. Limitations (explicit)

1. Equivalence proves **fact preservation**, not hint helpfulness: a
   passing B1 may still be useless (or harder to read) — that is the
   experiment's question, not the checker's.
2. The fact model covers only §2's thirteen dimensions. Render-pixel
   differences, font/wording tone, and hint readability are out of scope
   by design.
3. Ordinal panels (`scope::panel.<index>`) and spatial hints are
   second-class by construction (`persistent:false,
   authoritative:false`); samples whose disambiguation depends on them
   cannot yield strong presentation-effect claims.
4. Overlay samples with zero eligible descriptors (adverse G15 prior;
   image-only panels) contribute no READY A/B1 pair — at most a
   compare-only or REFUSE-role sample, decided by real preflight inventory,
   not by assumption.
5. Truncation-equivalence (post-truncation hashing) can only detect fact
   loss, not measure its behavioral impact; impact is the later experiment's
   estimand with its own pre-registered metrics.
6. This design assumes the current `PLAN_SCHEMA` single-route/single-scope
   boundary. Anything requiring cross-scope or cross-route atomic edits is
   a boundary sample by definition and MUST NOT be coerced into an A/B1
   READY pair.

---

## 9. Non-goals (this file does none of these)

- No implementation: no packet builder, extractor, canonicalizer, or
  checker code; no product edits to `edit_plan.py` / `plan_context.py` /
  `style_identity.py` / `style_overlay.py`; no `PLAN_SCHEMA` change.
- No test, build, or formatter run; no gate thresholds, pass percentages,
  or baseline comparisons (those freeze separately per protocol §停止与后续门禁).
- No model call, no prompt tuning, no gold authoring, no freeze claim —
  candidate/draft status is unchanged by reading or following this design.
- No new execution engine, agent, retry loop, GUI, Artist type, write
  permission, region layer, or QA relaxation.
- No JSON Schema file: per freeze-schema §11, cross-field/cross-file
  invariants (D1–D6) belong in a small checker implementing §6/§9, generated
  only when the freeze tooling needs it.

→ skipped: checker code, JSON Schema, B2 field registry; add when the
freeze tooling task lands with an independent annotator and real preflight
payloads to validate against.
