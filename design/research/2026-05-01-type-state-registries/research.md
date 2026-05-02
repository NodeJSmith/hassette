---
topic: "Type and State Registry Patterns"
date: 2026-05-01
status: Draft
---

# Prior Art: Type and State Registry Patterns

## The Problem

Frameworks that map external data to typed internal objects need registries — lookups that answer "given this domain string, which Python class handles it?" and "given this (source_type, target_type) pair, how do I convert?" The design choices determine extensibility (can users add their own mappings?), performance (how fast is lookup?), debuggability (why did the wrong handler get selected?), and correctness (what happens for unknown keys?).

The registry pattern seems simple — it's a dict — but the details matter: how do entries get into the dict (auto-registration vs explicit), how are keys structured (flat vs composite with fallback chains), how is the registry scoped (global vs per-instance), how does it interact with the import system (registration-on-import side effects), and how do you test code that depends on registry state? Every mature Python framework has at least one registry, and most have opinions about how to build them.

## How We Do It Today

Hassette has a **two-registry architecture**. The `StateRegistry` maps `StateKey(domain, device_class)` tuples to Pydantic state model classes, populated automatically via `__init_subclass__` on `BaseState` — when `class LightState(StringBaseState): domain: Literal["light"]` is defined, it auto-registers with domain extracted from the `Literal` type annotation. Lookup has a fallback chain: exact (domain, device_class) → domain-only → generic `BaseState`. The `TypeRegistry` maps `(source_type, target_type)` tuples to `TypeConverterEntry` objects containing the converter function, expected error types, and error message formatting. ~20 converters are registered at import time via decorator (`@register_type_converter_fn`) and explicit calls (`register_simple_type_converter`). Fallback: if no registered converter exists, attempts the target type's constructor before raising `UnableToConvertValueError`. Both registries support user extension.

## Patterns Found

### Pattern 1: `__init_subclass__` Auto-Registration

**Used by**: Many modern Python projects (3.6+), recommended replacement for metaclass registries

**How it works**: The base class defines `__init_subclass__(**kwargs)` which runs when any subclass is defined (at class creation time). The method registers the new subclass in a dict. Keyword arguments in the class definition (e.g., `class Dog(Animal, sound="woof")`) are forwarded, enabling declarative metadata. The `super().__init_subclass__(**kwargs)` chain provides free typo detection — unrecognized kwargs raise `TypeError`.

The key limitation: the module containing the subclass must be imported for registration to occur. Systems pair this with `autodiscover()` or explicit imports.

**Strengths**: Clean syntax. No metaclass conflicts. Built into the language. Typo detection via `super()` chain. Works with multiple inheritance.

**Weaknesses**: Registration depends on import side effects — missing import = missing registration (the most common bug). Debugging "why isn't my class registered?" is a missing-import problem.

**Example**: https://blog.yuo.be/2018/08/16/__init_subclass__-a-simpler-way-to-implement-class-registries-in-python/

### Pattern 2: Decorator-Based Registration

**Used by**: Flask (`@app.route`), Click, FastAPI, pytest, class-registry library

**How it works**: A decorator records the decorated function/class in a dictionary and returns it unchanged. The key is passed as a decorator argument (`@registry.register("json")`) or inferred from the decorated object. Explicit and visible at the definition site — you can see that a class is registered and under what key.

Some implementations combine decorators with `__init_subclass__` — the decorator handles explicit key assignment while `__init_subclass__` handles automatic discovery.

**Strengths**: Explicit at the definition site. Key declared alongside implementation. No metaclass conflicts. Works for functions. Supports multiple registrations.

**Weaknesses**: Still import-dependent. "Import for side effects" pattern. Registry object must exist before decorators reference it.

**Example**: https://blog.miguelgrinberg.com/post/the-ultimate-guide-to-python-decorators-part-i-function-registration

### Pattern 3: Metaclass-Based Registration

**Used by**: Django models (`ModelBase`), SQLAlchemy declarative base, older plugin systems

**How it works**: Custom metaclass overrides `__new__` or `__init__` to intercept class creation. Django's `ModelBase` populates `Apps.all_models` when any `Model` subclass is created, extracting `Meta` options and building the model's `_meta` object — all before the class body finishes executing.

**Strengths**: Most powerful — full control over class creation. Automatic, no action from subclass authors. Can enforce invariants at definition time.

**Weaknesses**: Metaclass conflicts prevent combining registries. Complex. Largely superseded by `__init_subclass__` for pure registration.

**Example**: https://github.com/faif/python-patterns/blob/master/patterns/behavioral/registry.py

### Pattern 4: Explicit `register()` Calls

**Used by**: Django admin, cattrs (`register_structure_hook`), many service registries

**How it works**: The registry exposes `register(key, value)` called explicitly during setup. Django admin: `admin.site.register(MyModel, MyModelAdmin)`. Also supports `unregister()` for removal/replacement. Favored when the same class needs different registrations in different contexts, or when unregistration matters.

**Strengths**: Most explicit and traceable. Supports unregistration/replacement. Works when the key is external to the class. Easy to test. Conditional registration.

**Weaknesses**: Boilerplate. Easy to forget. Requires coordination point that knows all registrations.

**Example**: https://charlesleifer.com/blog/looking-registration-patterns-django/

### Pattern 5: Multi-Strategy Dispatch (cattrs)

**Used by**: `functools.singledispatch`, cattrs (`MultiStrategyDispatch`), plum-dispatch

**How it works**: cattrs coordinates three strategies with defined precedence: (1) singledispatch for concrete classes, (2) direct dict lookup, (3) `FunctionDispatch` with predicates for generic/parameterized types (evaluated in reverse registration order). An LRU cache sits in front. Hook factories dynamically generate handlers for parameterized types (e.g., `list[int]` from the `int` hook and a list template).

Resolution: LRU cache → singledispatch (exact type) → direct dispatch (dict) → FunctionDispatch (predicates) → fallback factory. This handles the full spectrum of Python's type system — concrete types, generics, `Annotated`, `Literal`, `Protocol`.

**Strengths**: Handles full type system. Caching makes repeated lookups fast. Hook factories enable generalization. Clean strategy separation.

**Weaknesses**: Registration order matters (simpler types before complex). Predicate matching hard to debug when multiple match. Three-tier system is complex.

**Example**: https://deepwiki.com/python-attrs/cattrs/4.1-hook-registration-and-dispatch

### Pattern 6: Entry Points Plugin Registry

**Used by**: setuptools, pip, pytest, tox, flake8, mypy, class-registry library

**How it works**: Packages declare entry points in `pyproject.toml` under named groups. The host discovers plugins via `importlib.metadata.entry_points(group='myapp.plugins')` — lazy references only imported when `.load()` is called. Completely decouples registration from import-time effects.

**Strengths**: True third-party extensibility. Lazy loading. No import side effects. Packaging standard.

**Weaknesses**: Only works for installed packages. Discovery relatively slow. Requires packaging infrastructure.

**Example**: https://packaging.python.org/guides/creating-and-discovering-plugins/

### Pattern 7: Composite-Key and Multi-Index Registries

**Used by**: Home Assistant (entity registry), Django (`app_label + model_name`), database ORMs

**How it works**: Registry uses tuple/compound keys (e.g., `(domain, platform, unique_id)` in HA). Multiple parallel indexes support lookups from different angles. HA's entity registry maintains four concurrent indexes: primary key (entity_id), ID index, unique index, and device index. Fallback chains: specific key → general key → default.

**Strengths**: Multiple access patterns efficiently. Composite keys enforce multi-dimensional uniqueness. Fallback chains enable override cascades.

**Weaknesses**: Index maintenance overhead. Consistency between indexes must be enforced. More complex to test.

**Example**: https://deepwiki.com/home-assistant/core/2.2-entity-and-registry-management

### Pattern 8: Type Decorator / Wrapper Chain (SQLAlchemy)

**Used by**: SQLAlchemy (`TypeDecorator`), marshmallow (`TYPE_MAPPING`)

**How it works**: Instead of flat key-value, types form a chain via the decorator pattern. `TypeDecorator` wraps an existing type via `impl`, layering custom bind/result processing. The pipeline is bidirectional. Marshmallow's `TYPE_MAPPING` is a class attribute on Schema — subclasses inherit and override parent mappings, creating inheritance-scoped registries.

**Strengths**: Composable layers. Preserves underlying type functionality. Schema-scoped (marshmallow) avoids global state.

**Weaknesses**: Debugging requires understanding full chain. `cache_ok` must be declared for safety.

**Example**: https://docs.sqlalchemy.org/en/20/core/custom_types.html

## Anti-Patterns

- **Silent registration failure from missing imports**: Both `__init_subclass__` and decorator registries depend on import. A module added but never imported = classes silently unregistered. Most common bug with auto-registration. ([source](https://dev.to/dentedlogic/stop-writing-giant-if-else-chains-master-the-python-registry-pattern-ldm))

- **Registry as global mutable state**: Module-level dict registries create hidden dependencies invisible to static analysis. Components depending on registry contents have implicit coupling that breaks testing. ([source](https://www.baeldung.com/cs/dependency-injection-vs-service-locator))

- **Registration order dependencies**: In cattrs, hooks for simpler types must be registered before complex types that depend on them — factory-generated hooks cache dependencies at registration time. Violating this produces incorrect behavior silently. ([source](https://catt.rs/en/stable/customizing.html))

- **Thread-unsafe registry mutation**: Import-time population is safe (import lock serializes), but runtime mutation (register/unregister during request handling) needs synchronization. Django uses `threading.Event`; ad-hoc registries often skip this. ([source](https://github.com/django/django/blob/main/django/apps/registry.py))

## Emerging Trends

**Typed registries with Python 3.12+ generics**: `class Registry[Key, Value]` enables type-safe registries without `Generic` imports. IDE autocompletion and static checking for both keys and values — eliminates "registry returns Any." ([source](https://dev.to/dentedlogic/stop-writing-giant-if-else-chains-master-the-python-registry-pattern-ldm))

**Convergence on explicit registration**: The industry is moving from metaclass magic toward explicit mechanisms. `__init_subclass__` is the middle ground. Entry points for cross-package, `register()` for intra-package, `__init_subclass__` for inheritance — each with clear, non-overlapping use cases.

## Relevance to Us

Hassette's two-registry architecture is **well-designed and matches proven patterns**:

**What we're doing well:**

- **`__init_subclass__` for STATE_REGISTRY** (Pattern 1) — the modern Python approach. Domain extracted from `Literal` type annotations is clean and declarative. No metaclass conflicts.

- **Composite-key with fallback** (Pattern 7) — `StateKey(domain, device_class)` with fallback to domain-only then generic is the same pattern HA's entity registry uses. The fallback chain handles unknown device classes gracefully.

- **Dual registration strategy** — `__init_subclass__` for state models (inheritance-based) and decorators/explicit calls for type converters (function-based). Using different mechanisms for different registration needs is what Django does (metaclass for models, `register()` for admin).

- **Fallback to constructor** in TYPE_REGISTRY — when no converter is registered, trying `target_type(value)` is pragmatic and handles many cases (e.g., `int("42")`) without explicit registration.

- **User extensibility** — both registries support custom entries via subclassing (state models) or decorator/explicit registration (converters).

**Gaps worth examining:**

1. **No LRU cache on TYPE_REGISTRY lookup**: cattrs' `MultiStrategyDispatch` uses an LRU cache to avoid repeated resolution. Hassette's TYPE_REGISTRY does direct dict lookup, which is fast, but if the fallback-to-constructor path is hit frequently, caching successful fallback results would eliminate repeated `try/except` overhead.

2. **No readiness gate**: Django's app registry raises `AppRegistryNotReady` if accessed before `populate()` completes. Hassette's registries are populated at import time via `__init_subclass__`, which is generally safe, but there's no explicit guard against accessing the registry before all modules are imported. For a framework that supports auto-discovery (scanning for app files), this could matter if a state model's module is imported after a handler tries to convert its domain.

3. **No registration validation**: The current system accepts any registration silently. A `validate_registry()` step at startup — checking that all registered state models have valid domains, all converters have compatible type signatures — would catch configuration errors early. Django's `check()` framework does this for models.

4. **Missing import = silent gap**: The classic `__init_subclass__` pitfall. If a new state model file is created but not imported (no reference from `models/states/__init__.py`), it silently won't register. A startup check comparing registered domains against HA's known domains would catch this.

## Recommendation

Hassette's registries are well-designed — `__init_subclass__` for state models and decorator/explicit registration for type converters is the right dual strategy. The composite-key fallback chain for STATE_REGISTRY matches HA's entity registry pattern.

Two low-cost improvements:

1. **Startup validation** — a `validate_registries()` check that runs after all modules are imported, verifying that all registered converters have compatible types and all expected domains have registered models. Catches configuration errors and missing-import gaps at startup rather than at first use.

2. **LRU cache on TYPE_REGISTRY fallback path** — if the constructor-fallback path is hit (no registered converter but `target_type(value)` works), cache the result so subsequent lookups for the same type pair skip the `try/except`. Negligible implementation cost, measurable benefit under high-frequency conversion.

## Sources

### Reference implementations
- https://github.com/django/django/blob/main/django/apps/registry.py — Django app registry
- https://github.com/faif/python-patterns/blob/master/patterns/behavioral/registry.py — Python patterns registry
- https://docs.sqlalchemy.org/en/20/core/custom_types.html — SQLAlchemy TypeDecorator
- https://deepwiki.com/python-attrs/cattrs/4.1-hook-registration-and-dispatch — cattrs multi-strategy dispatch

### Blog posts & writeups
- https://blog.yuo.be/2018/08/16/__init_subclass__-a-simpler-way-to-implement-class-registries-in-python/ — __init_subclass__ registries
- https://charlesleifer.com/blog/looking-registration-patterns-django/ — Django registration patterns
- https://dev.to/dentedlogic/stop-writing-giant-if-else-chains-master-the-python-registry-pattern-ldm — Python registry pattern guide
- https://blog.miguelgrinberg.com/post/the-ultimate-guide-to-python-decorators-part-i-function-registration — Decorator registration

### Documentation & standards
- https://docs.djangoproject.com/en/4.2/ref/applications/ — Django app registry docs
- https://catt.rs/en/stable/customizing.html — cattrs converter customization
- https://deepwiki.com/home-assistant/core/2.2-entity-and-registry-management — HA entity registry
- https://packaging.python.org/guides/creating-and-discovering-plugins/ — Python plugin discovery
- https://class-registry.readthedocs.io/en/latest/entry_points.html — class-registry entry points
- https://docs.pydantic.dev/latest/concepts/unions/ — Pydantic discriminated unions
