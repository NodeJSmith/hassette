---
proposal: "Choose the argument shape for `hassette app config set` — a CLI command that writes persisted per-app config overrides at parity with the web UI's form-level (multi-field, one-restart) save."
date: 2026-08-11
status: Draft
flexibility: Exploring
motivation: "The web UI can save several config fields atomically, causing one app restart. The CLI has no write path at all. Whatever shape is chosen must express: 1-2 scalar edits, structured values (list/object/dict), and reverting a field to its file value."
constraints: "Full functional parity with a form-level web save — multiple fields changed atomically in one operation, one app restart. Values validated server-side against a Pydantic model (type coercion available). Secrets excluded from editing. CLI is cyclopts 4.15.0 (pinned >=4.0,<5.0)."
non-goals: "Editing secrets. Editing global (non-per-app) config. Designing the server endpoint."
depth: deep
---

# Research Brief: Argument Shape for `hassette app config set`

**Initiated by**: "what should the write command's argument shape be? Specifically how to express (a) the common case of one or two scalar edits, (b) a structured value (list/object/dict), and (c) reverting a field to its file value."

## Context

### What prompted this

hassette has read-only config commands (`hassette config`, `hassette app config <app_key>`) and a web UI that does form-level saves. Adding a CLI write path means picking an argument grammar, and that grammar is close to unchangeable once shipped — every tool surveyed here that got it wrong either accreted flags for years (helm: 5 variants over 11 years) or shipped a breaking change (npm 9, git 2.46).

### Current state (verified by reading the code)

Four facts from `/home/jessica/source/hassette/.claude/worktrees/runtime-param-friction/src/hassette/cli/` constrain the design. These are Direct-tier — read from source, not inferred.

1. **`--json` is already taken, at the meta level.** `cli/__init__.py:120` defines `--json` on `app.meta.default` as a *global output-format* flag. This directly eliminates npm's `npm pkg set --json` design (a `--json` modifier that switches *input value* interpretation). In hassette, `--json` already means "print output as JSON," and overloading it to also mean "parse my input values as JSON" would be genuinely ambiguous.
2. **`--instance` already exists** as `InstanceArg` (`cli/types.py:104`), resolved via `client.resolve_instance(key, instance)` (`cli/commands/app.py:71`). A write command should reuse it verbatim.
3. **Commands are plain functions** registered via `apps_app.command(fn, name=...)`, with `ctx` injected by the meta launcher (`cli/__init__.py:155`). Adding `set`/`unset` is two registrations, no structural change.
4. **The CLI already receives the full JSON Schema.** `AppConfigResponse.config_schema` (`web/models.py:509`) is "the fully-inlined config schema," fetched today by `cmd_app_config` and deliberately not rendered. `app_config` is `dict[str, Any] | list[dict[str, Any]]` — the list form is the multi-instance case. This is a significant, underused asset: the CLI can consult field types locally for error messages and shell completion without a round trip.

### Key constraints

- **Atomicity is a hard requirement, not an ergonomic nicety.** Parity with a form-level save means N fields → one write → one restart. This constraint alone rules out several otherwise-conventional designs (see Concerns).
- Server-side Pydantic validation and coercion are available. **This is the single most important asymmetry between hassette and the cautionary precedents below.**

## Feasibility Analysis

### What already supports this

- The `set`/`unset` commands slot into the existing `apps_app` sub-App with no restructuring.
- `InstanceArg` + `resolve_instance` handle multi-instance targeting already.
- `config_schema` is already on the wire.
- **Server-side coercion removes the entire class of problem that produced helm's flag sprawl.** Helm needed `--set-string` because it guessed types client-side and guessed wrong (helm/helm#2848: "the value `true`, `false` and numbers get parsed into their typed values" when the user wanted the literal string). hassette never has to guess: the server knows `port` is `int` and `name` is `str`, so `port=8080` and `name=true` both resolve correctly with zero client-side type machinery.

### What works against this

- The `--json` name collision (above) forecloses the cleanest precedent for an input-type modifier.
- `app_config` typed as `dict[str, Any]` means genuinely `Any`-typed or union-typed (`str | list[str]`) fields are representable in an `AppConfig`. For those fields, no schema-driven disambiguation is possible, and an escape hatch is required. **Confidence: Inferred** — I did not enumerate real `AppConfig` subclasses to measure how common such fields actually are. See Open Questions.

### cyclopts capability — empirically verified, not assumed

I ran throwaway probes against the pinned cyclopts 4.15.0 in hassette's own venv (`/home/jessica/source/hassette/.venv`) rather than trusting docs. Scripts are at `/tmp/claude-1000/-home-jessica-source-hassette/a1475703-bc90-49fc-a6e3-60bba74e8905/scratchpad/probe_cyclopts.py`, `probe2.py`, `probe3.py`. Results:

| Shape probed | Result |
|---|---|
| `*pairs: str` variadic positional | **Works.** `set myapp foo=1 bar=2` → `('foo=1', 'bar=2')` |
| Variadic + keyword flags interleaved in any order | **Works.** `myapp --unset baz bar=2` → `pairs=('bar=2',) unset=['baz']`; `myapp --instance office --unset a x=1` parses correctly. No silent misparse in any ordering tested. |
| Value with leading hyphen (`offset=-5`) | **Works** — the token doesn't start with `-`, so no `allow_leading_hyphen` needed |
| Value containing `=` (`note=a=b`) | **Works** — passes through whole; split on first `=` in the handler |
| Empty value (`note=`) | **Works** |
| JSON in a positional value (`sensors=["a","b"]`) | **Works** — arrives as an opaque string |
| `list[str]` flag, repeated (`--set a=1 --set b=2`) | **Works** (cyclopts default) |
| `list[str]` flag, multi-token (`--set a=1 b=2`) | **Errors** by default (`UnusedCliTokensError`); works with `consume_multiple=True` |
| `dict[str,str]` via dotted keys (`--values.foo 1`) | **Works** → `{'foo': '1'}` |
| **JSON blob into a `dict[...]` param** | **FAILS in every configuration tested** |
| `list[str]` with `json_list=True` (`--values '["a","b"]'`) | **Works** |
| `Parameter(help=...)` on a variadic positional | **Works** — renders in an "Arguments" panel |

**The JSON-into-dict failure is the load-bearing negative result.** `--values '{"a": 1}'` raises `CoercionError: unable to convert "{"a": 1}" into dict[str, Any]` across `dict[str,str]`, `dict[str,Any]`, `dict[str,int]`, with and without `| None`, with `json_dict=True`, with `accepts_keys=False`, and in both `--values {json}` and `--values={json}` forms. cyclopts' `json_dict` applies to *dataclass-like* parameters, not to plain `dict[...]` annotations. **This kills any design that expects a cyclopts-native dict parameter to also accept a JSON object.**

One gotcha to note: a `list[str]` parameter auto-generates a negative flag (`--empty-unset` for a param named `unset`). Suppress with `Parameter(negative=[])`.

## Precedent Survey

### The single strongest signal: tools that changed their syntax

Three tools migrated from shape A to shape B on exactly this axis. All three moved the same direction.

**helm — accreted five variants because it had no schema.** `--set` (2016) → `--set-string` (type inference guessed wrong on `true`/`1234567890`) → `--set-file` (values too long for a command line) → `--set-json` (merged [helm/helm#10693](https://github.com/helm/helm/pull/10693), 2022-08-31, shipped 3.10.0) → `--set-literal` ([helm/helm#9182](https://github.com/helm/helm/pull/9182), merged 2023-04-28, shipped 3.12.0, closing an escaping bug filed in 2018).

The `--set-json` rationale is the most directly relevant document in this whole survey. [helm/helm#10428](https://github.com/helm/helm/issues/10428) opened with a user unable to set a nested structure, forced to flatten it into leaf assignments:

> `'spec.sNssaiUpfInfoList[0].sNssai.sd=0002f0,spec.sNssaiUpfInfoList[0].sNssai.sst=1,spec.sNssaiUpfInfoList[0].dnnUpfInfoList[0].dnn=intranet, ...'`

> "This is not very flexible because extra logic is required to translate the data structure into individual key=val for each of its leaf attributes."

The same gap was reported independently three years earlier ([helm/helm#5618](https://github.com/helm/helm/issues/5618), 2019), where a user passing a service-account JSON key through `--set-string` got `wrong type for value; expected string; got []interface {}` and had to escape every brace and comma:

> "But inside our CI pipeline I do not want to have some magical escaping on environment variables."

helm's own docs concede the ceiling: *"Deeply nested data structures can be difficult to express using `--set`."* ([Using Helm](https://helm.sh/docs/intro/using_helm/#the-format-and-limitations-of---set))

**The lesson is not "avoid `key=value`."** It is "avoid `key=value` *without a schema*." Every one of helm's five variants exists to compensate for the client not knowing the target type. hassette's server does know.

**npm 9 — moved `key value` → `key=value`.** Current docs: `npm config set key=value [key=value...]`, with "npm config set key value is supported as an alias." The likely trigger is [npm/cli#2072](https://github.com/npm/cli/issues/2072), where the positional two-arg form let a value containing an env-var reference corrupt a *different* previously-set key. **Confidence: Inferred** — the bug report is real and the shapes match, but I did not find the PR/RFC that explicitly cites it as the motivation. Treat the causal link as plausible, not established.

**git 2.46 (July 2024) — moved `--unset` flag → `unset` subcommand.** Release notes: *"The operation mode options (like `--get`) the `git config` command uses have been deprecated and replaced with subcommands (like `git config get`)."* Current docs map `--unset <name>` → "Replaced by `git config unset [--value=<pattern>] <name>`." ([git-config](https://git-scm.com/docs/git-config), [2.46.0 release notes](https://github.com/git/git/blob/v2.46.0/Documentation/RelNotes/2.46.0.txt))

### Multi-field atomicity

| Tool | Multi-field in one call? | Syntax |
|---|---|---|
| `az config set` | **Yes** | `az config set defaults.location=westus2 defaults.group=MyResourceGroup` (variadic positional) |
| `npm config set` | **Yes** | `npm config set key=value [key=value...]` |
| `npm pkg set` | **Yes** | `npm pkg set description='Awesome package' engines.node='>=10'` |
| `kubectl set env` | **Yes** | `kubectl set env RESOURCE/NAME KEY_1=VAL_1 ... KEY_N=VAL_N` |
| `systemctl set-property` | **Yes** | `systemctl set-property httpd.service CPUShares=600 MemoryLimit=500M` |
| `helm --set` | **Yes** | repeated flag and/or comma-separated |
| `git config` / `gcloud config set` / `aws configure set` | **No** — one at a time | |

**Two findings matter here.**

First: **every tool that supports batching uses `key=value` tokens. Not one batches with positional `key value key value`.** That shape is apparently considered too ambiguous to extend past a single pair — consistent with the npm bug above.

Second, and directly on hassette's atomicity requirement: `systemd`'s docs state the case explicitly —

> "This command allows changing multiple properties at the same time, which is preferable over setting them individually."

That is precedent for treating batched writes as a correctness feature when each call carries a side effect. The counterexample is [moby/moby#32344](https://github.com/moby/moby/issues/32344), where env-var updates on `docker service update` caused spurious service restarts — confirming that per-call restart side effects are a real hazard, not a hypothetical one.

The one-at-a-time holdouts (git, gcloud, aws) are the three oldest config CLIs surveyed, and none of them has a restart side effect per write. **hassette does.** The precedent that best matches hassette's constraint is `systemctl set-property` / `kubectl set env`, not `gcloud config set`.

### The string-vs-structured split

| Tool | Default | Escape hatch | Mechanism |
|---|---|---|---|
| jq | `--arg` = string | `--argjson` = parsed JSON | **separate flag name** |
| helm | `--set`, type-guessed | `--set-json`, `--set-string`, `--set-literal`, `--set-file` | four separate flags |
| ansible | `-e key=value` (strings) | `-e '{json}'` or `-e @file.yml` | alternate syntax, same flag |
| npm pkg set | string | `--json` modifier | flag toggles parse mode |
| httpie | `field=value` | `field:=json` | **sigil on the token** |
| gh api | `-f` = raw string | `-F` = type-coerced + `@file` | case-differentiated flag |
| terraform | string, *unless* the declared type is non-primitive | same flag, HCL-in-string | **implicit, driven by target schema** |

Ansible states the rule that every schemaless tool eventually has to write down:

> "Values passed in using the `key=value` syntax are interpreted as strings. Use the JSON format if you need to pass non-string values such as Booleans, integers, floats, and lists." ([Ansible variables docs](https://docs.ansible.com/ansible/latest/playbook_guide/playbooks_variables.html))

**Terraform is the closest structural analogue to hassette** (typed schema + CLI strings) and is worth studying as a *warning about error messages, not about the model itself*. Its rule — parse the value as HCL only if the variable's declared type is non-primitive — is exactly the schema-driven model hassette can use. It works correctly; the recurring complaints are about *legibility*. [hashicorp/terraform#17032](https://github.com/hashicorp/terraform/issues/17032) shows a user failing three times in a row:

```
terraform plan -var myvar="zzzz"        # → should be type list, got string
terraform plan -var myvar=["zzzz"]      # → Cannot parse value ... unexpected token
terraform plan -var 'myvar=["zzzz"]'    # → same parsing error
```

And [HashiCorp Discuss #49058](https://discuss.hashicorp.com/t/cannot-pass-complex-variable-type-on-command-line/49058) shows the same confusion, where the answer turned out to be that the *declared type* silently governs parsing. Terraform's docs also concede defeat on shell quoting: *"PowerShell on Windows cannot correctly pass literal quotes to external programs, so we do not recommend using Terraform with PowerShell when you are on Windows."*

The mitigation is available to hassette and was not available to Terraform: hassette already ships `config_schema` to the client, so the CLI can say *"field `sensors` is `list[str]`; the value could not be parsed as JSON: ..."* instead of Terraform's opaque parser error.

**On sigils (httpie's `:=`)** — the balanced read from the research is that the sigil *table* is considered learnable; the complaints target the implicit *default* (bare `=` silently building a JSON body). From the [HN thread](https://news.ycombinator.com/item?id=21674729): defenders call it "fully documented and quite easy to follow," while critics call it "opaque magic" that "switches around between HTTP methods, content types, query building... at every minor syntactic change." Notably httpie *added* to the grammar twice (`=@`/`:=@` in 0.8.0, 2014; the entire bracket-path nested-JSON sub-grammar in 3.0.0, 2022) — and then shipped an escaping bugfix for the new sub-grammar one release later ([httpie/cli#1285](https://github.com/httpie/cli/issues/1285)). Sigil grammars grow.

**On case-differentiated flags (`gh api -f`/`-F`)** — this is the same string-vs-typed split hassette faces, and it is the design I would most confidently tell hassette *not* to copy. [cli/cli#8983](https://github.com/cli/cli/issues/8983) documents a user unable to pass an int or bool and discovering the capital-`F` variant only by trial and error. Nothing in the error output points at the other case.

### Reverting / unsetting

| Mechanism | Tools |
|---|---|
| Dedicated `unset`/`delete` subcommand | git (≥2.46), gcloud, az, pip, `npm pkg delete`, `gh secret delete`; `npm config delete key [key...]` is variadic |
| Sentinel value | kubectl (`KEY-`), helm (`=null`), docker compose (`KEY:`) |
| **No unset at all** | `aws configure`, `gh config` |

**The subcommand is the convergent modern convention**, and git's 2024 migration *toward* it is the strongest single data point. But the tally hides a pattern that matters more for hassette: **every tool using a sentinel is a tool where set and unset must interleave inside one multi-value call** (env vars, helm values overlays). The sentinel exists precisely because a separate subcommand cannot compose inline. That is hassette's situation exactly.

Omitting unset is a documented failure: [aws/aws-cli#3346](https://github.com/aws/aws-cli/issues/3346) has been open since 2018 asking for one, with [#9876](https://github.com/aws/aws-cli/issues/9876) closed as a duplicate.

kubectl's sentinel has its own documented problems, which argue against copying the trailing-dash specifically: [kubernetes/kubectl#577](https://github.com/kubernetes/kubectl/issues/577) (`--prefix` silently ignored on the removal path, so `FOO-` removes the wrong variable) and [kubernetes/kubernetes#39775](https://github.com/kubernetes/kubernetes/issues/39775) (users requesting a real `unset` verb).

**"Unset everything" has essentially no precedent.** Nothing surveyed offers "revert all overrides." The closest are scope-broadeners (`gcloud --installation`) or structural deletion (`git config remove-section`).

## Options Evaluated

### Option A (recommended): variadic positional `FIELD=VALUE`, schema-driven coercion, `--unset` on `set` plus a thin `unset` subcommand

**How it works.** `set` takes a variadic positional of `FIELD=VALUE` tokens. Values go to the server as strings; the server coerces each against the Pydantic field type. For a non-scalar target type, the server parses the string as JSON. Because the target type is known, `sensors='["a","b"]'` becomes a list for a `list[str]` field and stays a string for a `str` field — **no client-side sigil or type flag is needed for the structured case at all.** Reverts ride along on the same call via a repeatable `--unset`, preserving atomicity; a separate `unset` subcommand exists for discoverability and delegates to the same endpoint.

```bash
# (a) the common case — one or two scalars
hassette app config set climate_manager target_temp=72
hassette app config set climate_manager target_temp=72 mode=heat

# (b) structured values — plain JSON in the value, no sigil, no extra flag
hassette app config set climate_manager sensors='["sensor.a","sensor.b"]'
hassette app config set climate_manager schedule='{"mon":"08:00","tue":"09:00"}'

# (c) revert a field to its file value
hassette app config unset climate_manager target_temp
hassette app config unset climate_manager target_temp mode      # variadic, like npm config delete

# the parity case: set + revert, ONE write, ONE restart
hassette app config set climate_manager mode=heat --unset target_temp

# escape hatch: ambiguous (Any / union) fields, large payloads, scripting
hassette app config set climate_manager --from-json ./overrides.json
generate-config | hassette app config set climate_manager --from-json -

# existing CLI conventions carried over
hassette app config set climate_manager target_temp=72 --instance office
hassette app config set climate_manager target_temp=72 --dry-run
```

Verified-working cyclopts signature (every construct below was exercised in the probes):

```python
def cmd_app_config_set(
    key: str,
    *pairs: Annotated[str, Parameter(help="FIELD=VALUE assignments. Repeatable.")],
    unset: Annotated[list[str] | None, Parameter(name=["--unset"], negative=[], help="Revert FIELD to its file value.")] = None,
    from_json: Annotated[str | None, Parameter(name=["--from-json"], help="Read a {field: value} object from FILE, or - for stdin.")] = None,
    instance: InstanceArg = None,
    dry_run: Annotated[bool, Parameter(name=["--dry-run"], negative=[])] = False,
    ctx: CLIContextParam = DEFAULT_CLI_CONTEXT,
) -> None:
```

**Pros**
- Only shape with *unanimous* precedent for batching: az, npm config, npm pkg, kubectl, systemctl all use variadic `key=value`. Zero tools batch any other way.
- Atomic set+revert in one call satisfies the parity requirement directly, matching `systemctl set-property`'s explicit "preferable over setting them individually" rationale and avoiding the per-call-restart hazard that bit moby/moby#32344.
- **Sidesteps helm's entire failure mode by exploiting the schema.** No `--set-string`, no `-f`/`-F`, no `:=`. The four-to-five-flag sprawl in helm and the case-collision confusion in `gh api` both trace to a client that must guess; hassette's does not.
- Avoids the `--json` name collision entirely — no input-mode flag is needed.
- Field names are Python identifiers, so they can contain neither `=` nor `.`-with-ambiguity. **Splitting on the first `=` is unambiguous, and no key escaping is ever required** — structurally better off than helm, whose keys can be dotted k8s annotations and which needed `\.` and `\,` escaping (and still shipped [#12981](https://github.com/helm/helm/issues/12981), a residual escaping bug in `--set-literal` itself).
- Probes confirm no ordering of positionals and flags misparses.

**Cons**
- Superficially resembles `helm --set`, which invites the "you'll end up with five flags too" objection. The rebuttal is real (schema) but requires explaining.
- Structured values need shell quoting. Unavoidable in every option here, and in every tool surveyed.
- Schema-driven parsing is Terraform's model, and Terraform's users are visibly confused by it. **Mitigation is mandatory, not optional**: error messages must name the field's declared type, using the `config_schema` the CLI already receives.
- Genuinely `Any`-typed fields have no in-band disambiguation and must fall back to `--from-json`.

**Effort estimate**: Small on the CLI side — two command registrations, a `partition("=")` loop, reuse of `InstanceArg`. The endpoint and restart semantics are the real work and are out of scope here.

**Dependencies**: None new.

### Option B: repeated `--set FIELD=VALUE` flag

```bash
hassette app config set climate_manager --set target_temp=72 --set mode=heat
```

**How it works.** Identical semantics to A, but assignments arrive through a repeatable `list[str]` flag instead of positionally. This is helm's shape and the cyclopts-native list shape.

**Pros**
- Probed working with zero cyclopts configuration; `consume_multiple=True` optionally allows `--set a=1 b=2`.
- The flag name self-documents in `--help` as a single row.
- Leaves the positional slot free.

**Cons**
- Strictly more typing than A for the dominant case, with no compensating benefit — `--set` carries no information once you are already inside a command named `set`. The stutter (`config set ... --set`) is a real readability wart.
- No batching precedent among config-setting CLIs uses this shape; it comes from helm, an *overlay* tool, not a config store.
- Historically the shape that attracts sibling flags (`--set-json`, `--set-string`). Having `--set` present makes `--set-json` the locally obvious next move, whereas A has no such gravitational pull.

**Effort estimate**: Small — marginally simpler than A.

### Option C: cyclopts-native dict binding `--values.FIELD VALUE`

```bash
hassette app config set climate_manager --values.target_temp 72 --values.mode heat
```

**How it works.** A `dict[str, str]` parameter; cyclopts binds `--values.KEY VALUE` natively.

**Pros**
- Zero custom parsing — this is cyclopts' flagship dict example.
- No `=` splitting, so no theoretical key/value ambiguity.

**Cons**
- **Disqualifying: cannot express structured values.** Probes show JSON into a `dict[...]` param fails in every configuration (`json_dict=True`, `accepts_keys=False`, both `--values {json}` and `--values={json}` forms) because cyclopts' `json_dict` targets dataclass-like params, not `dict[...]`. Requirement (b) would need a second, differently-shaped flag — reintroducing exactly the helm sprawl A avoids.
- Zero precedent. No surveyed CLI sets config this way; it would be unlike every tool a hassette user already knows.
- `--values.target_temp` is more keystrokes than `target_temp=` and reads worse.
- Shell completion cannot suggest dynamic keys after `--values.`.

**Effort estimate**: Small to implement, but it does not satisfy the requirements.

## Concerns

### Technical risks

- **Schema-driven parsing is invisible at the call site.** This is Terraform's documented failure ([#17032](https://github.com/hashicorp/terraform/issues/17032), [Discuss #49058](https://discuss.hashicorp.com/t/cannot-pass-complex-variable-type-on-command-line/49058)). A user typing `sensors='["a","b"]'` has no way to know from the command line whether it lands as a list or a string. The countermeasure — error messages naming the declared type, sourced from `config_schema` — is a requirement of Option A, not a nice-to-have. If it is cut, Option A degrades into Terraform's UX.
- **`Any`-typed and union-typed fields have no in-band answer.** `--from-json` covers them, but only if the failure mode points there. **Confidence: Inferred** — I did not measure how often such fields occur in real `AppConfig` subclasses.
- **`--dry-run` is listed above without precedent research.** I did not survey dry-run conventions; it is included because a write command that triggers restarts plausibly wants one, not because evidence demands it.

### Complexity risks

- Two surfaces (`FIELD=VALUE` pairs and `--from-json`) instead of one. This mirrors ansible's `key=value` + `@file` split and helm's `--set` + `-f`, so it is conventional — but it is still two things to document.
- A thin `unset` subcommand duplicating `--unset` is redundant surface. The justification is discoverability (aws's missing unset has been an open issue since 2018) and the fact that pure-revert is a common standalone action. It is a defensible ~5-line delegation, but it *is* the kind of convenience API that warrants explicit justification rather than reflexive addition.

### Maintenance risks

- **The grammar is effectively permanent.** helm has spent eleven years and five flags failing to escape its initial `--set` design. Whatever ships here should be assumed unchangeable.
- Every future non-scalar type in `AppConfig` must round-trip through JSON-in-a-string. Fine for JSON-representable types; a type that is not JSON-representable would have no CLI path.

### The strongest argument against my own recommendation

**Option A bets everything on the server-side schema, and that bet is what distinguishes it from helm's `--set` — but hassette's schema is weaker than the argument assumes.**

The claim "hassette never has to guess the type" holds only for fields with concrete annotations. `AppConfigResponse.app_config` is typed `dict[str, Any]`, and nothing prevents an app author from declaring `Any`, `str | list[str]`, or a permissive union. For every such field, Option A degrades to exactly helm's position — an untyped string with no way to signal intent — and the escape hatch is a *whole-payload* flag (`--from-json`), which is a much heavier fallback than helm's per-value `--set-json`.

If ambiguous fields turn out to be common rather than rare, the pressure to add a per-pair JSON escape (`--set-json`, or a `:=` sigil) will be immediate, and hassette will have started down helm's exact path with the added handicap of having already spent the positional slot. A design that acknowledged this from the start — for instance, shipping the `:=` sigil in v1 so the escape hatch is per-pair rather than per-payload — would be more honest about the failure mode even though it is uglier on day one.

**This is the single most important thing to check before implementing**, and it is checkable: enumerate the field annotations across real `AppConfig` subclasses and count how many are `Any` or permissive unions. If that number is near zero, Option A is safe as written. If it is not, revisit.

## Open Questions

- [ ] **How many real `AppConfig` fields are `Any`-typed or permissively unioned?** I did not enumerate `AppConfig` subclasses. This is the decisive input for the counter-argument above and is answerable by reading the codebase plus the example apps.
- [ ] Does the server endpoint parse JSON strings for non-scalar fields today, or would Option A require adding that? Endpoint design was out of scope; I found no existing config-override write plumbing (grep for `config_override`/`overrides` in `src/hassette/web/` and `src/hassette/config/` returned nothing).
- [ ] Should `unset --all` exist? **No precedent found in any surveyed tool** — nothing offers "revert every override." That absence is itself a signal, but hassette's overrides are a thinner layer than a full config file, so it may be more reasonable here than elsewhere.
- [ ] Multi-instance semantics: when `--instance` is omitted on an app with several instances, does `set` write to all of them or error? `AppConfigResponse.app_config` being `dict | list[dict]` implies both shapes exist. Erring toward an explicit error seems safer, but this is a product call.
- [ ] Is `--dry-run` wanted? Not researched.
- [ ] Should the CLI validate field names locally against `config_schema` before the round trip? It has the schema already; this would turn a server 4xx into an instant "no such field `targt_temp` — did you mean `target_temp`?"

## Recommendation

**Ship Option A**, with the type-naming error messages treated as part of the deliverable rather than a follow-up.

The reasoning that carries the most weight is not "variadic `key=value` is popular" — it is that **hassette's constraint set is a near-exact match for `systemctl set-property` and `kubectl set env`, and a poor match for `gcloud config set`.** hassette writes several fields at once, each write has a restart side effect, and reverts must compose inline with sets. Every tool in that situation converged on variadic `key=value` with inline revert. Every tool that chose one-at-a-time `key value` (git, gcloud, aws) has no per-write side effect to amortize.

The convergent "unset should be a subcommand" convention is real and I would normally follow it, but hassette's atomicity requirement overrides it: a separate subcommand cannot revert one field and set another in a single restart. Hence `--unset` on `set` for composition, plus a subcommand alias for discoverability — which is precisely why kubectl, helm, and compose all grew sentinels despite the broader convention.

Two claims I want to be explicit about hedging. First, the npm 9 causal story (positional ambiguity → `key=value`) is **Inferred**: the bug report matches the shapes but I found no maintainer statement citing it. Second, whether Option A's schema bet holds depends entirely on the `Any`-typed-field count, which I did not measure — that is a real hole in this recommendation, not a formality.

I would explicitly **not** copy: `gh api`'s `-f`/`-F` case distinction (documented confusion, cli/cli#8983), kubectl's trailing-dash unset (kubectl#577, kubernetes#39775), or npm's `--json` value-mode modifier (name already taken by hassette's global output flag).

### Suggested next steps

1. **Answer the blocking question first**: enumerate field annotations across real `AppConfig` subclasses and count `Any`/permissive-union fields. If more than a handful, reopen the per-pair-escape-hatch decision (`:=` or `--set-json`) before writing code.
2. Confirm the server endpoint's coercion contract — specifically whether it parses JSON strings for non-scalar targets — since Option A depends on it.
3. Write the design doc (`/mine-define`), fixing: multi-instance semantics with `--instance` omitted, the `--from-json` payload shape, and the exact error-message format that names declared field types.
4. Prototype the error messages against `config_schema` before building the happy path. Terraform's failure was never the model; it was the diagnostics.

## Sources

- helm: [Using Helm — `--set` format and limitations](https://helm.sh/docs/intro/using_helm/#the-format-and-limitations-of---set) · [values files](https://helm.sh/docs/chart_template_guide/values_files/) · [helm install reference](https://helm.sh/docs/helm/helm_install/) · [#10428](https://github.com/helm/helm/issues/10428) · [#10693](https://github.com/helm/helm/pull/10693) · [#5618](https://github.com/helm/helm/issues/5618) · [#2848](https://github.com/helm/helm/issues/2848) · [#4030](https://github.com/helm/helm/issues/4030) · [#9182](https://github.com/helm/helm/pull/9182) · [#12981](https://github.com/helm/helm/issues/12981)
- kubectl: [set env reference](https://kubernetes.io/docs/reference/kubectl/generated/kubectl_set/kubectl_set_env/) · [configmap task](https://kubernetes.io/docs/tasks/configure-pod-container/configure-pod-configmap/) · [patch task](https://kubernetes.io/docs/tasks/manage-kubernetes-objects/update-api-object-kubectl-patch/) · [kubectl#577](https://github.com/kubernetes/kubectl/issues/577) · [kubernetes#39775](https://github.com/kubernetes/kubernetes/issues/39775) · [kubectl#1014](https://github.com/kubernetes/kubectl/issues/1014)
- httpie: [request items](https://httpie.io/docs/cli/request-items) · [escaping behavior](https://httpie.io/docs/cli/escaping-behavior) · [CHANGELOG](https://github.com/httpie/cli/blob/master/CHANGELOG.md) · [#1285](https://github.com/httpie/cli/issues/1285) · [HN discussion](https://news.ycombinator.com/item?id=21674729)
- gh: [gh config](https://cli.github.com/manual/gh_config) · [gh config set](https://cli.github.com/manual/gh_config_set) · [gh secret set](https://cli.github.com/manual/gh_secret_set) · [gh api](https://cli.github.com/manual/gh_api) · [cli/cli#8983](https://github.com/cli/cli/issues/8983)
- cloud CLIs: [aws configure set](https://docs.aws.amazon.com/cli/latest/reference/configure/set.html) · [aws/aws-cli#3346](https://github.com/aws/aws-cli/issues/3346) · [gcloud config set](https://cloud.google.com/sdk/gcloud/reference/config/set) · [gcloud config unset](https://cloud.google.com/sdk/gcloud/reference/config/unset) · [az config](https://learn.microsoft.com/en-us/cli/azure/config)
- git/npm/pip: [git-config](https://git-scm.com/docs/git-config) · [git 2.46.0 release notes](https://github.com/git/git/blob/v2.46.0/Documentation/RelNotes/2.46.0.txt) · [Highlights from Git 2.46](https://github.blog/open-source/git/highlights-from-git-2-46/) · [npm-config](https://docs.npmjs.com/cli/v10/commands/npm-config) · [npm-pkg](https://docs.npmjs.com/cli/v10/commands/npm-pkg) · [npm/cli#2072](https://github.com/npm/cli/issues/2072) · [pip config](https://pip.pypa.io/en/stable/cli/pip_config/)
- terraform: [input variables](https://developer.hashicorp.com/terraform/language/values/variables) · [hashicorp/terraform#17032](https://github.com/hashicorp/terraform/issues/17032) · [HashiCorp Discuss #49058](https://discuss.hashicorp.com/t/cannot-pass-complex-variable-type-on-command-line/49058)
- docker/ansible/jq/systemd: [docker run](https://docs.docker.com/reference/cli/docker/container/run/) · [compose environment](https://docs.docker.com/reference/compose-file/services/#environment) · [moby/moby#32344](https://github.com/moby/moby/issues/32344) · [ansible variables](https://docs.ansible.com/ansible/latest/playbook_guide/playbooks_variables.html) · [jq manual](https://jqlang.org/manual/) · [systemctl set-property](https://www.freedesktop.org/software/systemd/man/systemctl.html)
- cyclopts: [rules](https://cyclopts.readthedocs.io/en/latest/rules.html) · [parameters](https://cyclopts.readthedocs.io/en/latest/parameters.html) · [api](https://cyclopts.readthedocs.io/en/latest/api.html) · [releases](https://github.com/BrianPugh/cyclopts/releases) — plus direct empirical probes against cyclopts 4.15.0
