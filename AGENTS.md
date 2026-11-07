# AGENTS.md — CBUS Workbench

## 1. Project philosophy

CBUS Workbench is a small, interactive Python/PySide6 utility for configuring and maintaining CBUS/VLCB networks.

**Simplicity, readability, traceability and developer understanding take precedence over architectural sophistication.**

- Implement only approved requirements. Prefer straightforward Python and standard Qt facilities.
- Do not introduce speculative features, frameworks, plugin systems, event buses or elaborate recovery mechanisms.
- Use existing platform capabilities rather than recreating them. Delete unnecessary code.
- Working code that is unnecessarily complicated is defective code.
- The previous JavaScript implementation is a behavioural reference, not an architectural template.

## 2. Developer ownership — Mandatory

The developer is learning Python and must be able to understand, challenge, debug and modify the application independently.

- Write clear, idiomatic Python; explain unfamiliar Python/Qt concepts when introduced.
- Keep functions focused, execution flow clear and names meaningful. Use type hints and dataclasses where helpful.
- Avoid unnecessary cleverness, decorators, metaclasses, inheritance and abstraction.
- Before significant implementation, explain the design and affected files. Afterwards, explain important code and decisions.
- Allow developer review and challenge before proceeding.

**The developer must not become dependent on Codex for trivial modifications.**

## 3. Outside-in development — Mandatory

1. Build the smallest useful PySide6 interface with representative stubbed data.
2. Review and approve the user experience.
3. Define the minimal API contract required by that interface.
4. Implement real behaviour behind that contract.
5. Repeat for the next capability.

Do not build backend functionality for anticipated screens. Keep stubs small, not elaborate simulators. Separate GUI, CBUS operations and persistence through a few clear boundaries. Respect protocol and hardware-safety constraints.

## 4. Logging and diagnostics — Mandatory

Logging must allow reconstruction of the execution path leading to a failure wherever practical.

- Use standard Python `logging` with a project-defined `TRACE` level.
- Write persistent, rotating logs; enable detailed file tracing by default with sensible size limits.
- At TRACE, record meaningful method entry/exit, relevant arguments/results, significant branches and reasons, state changes, and CBUS exchanges.
- Include layout, node and operation identifiers where relevant.
- Record full exception tracebacks; enable Python `faulthandler` for additional fatal-error diagnostics.
- Never log credentials or other sensitive data. Avoid custom logging frameworks and tracing trivial methods indiscriminately.

**A feature is not complete unless its significant execution and failure paths can be followed through logs.**

## 5. Comments and documentation — Mandatory

- Explain complicated or non-obvious logic, especially *why* decisions were made and protocol/hardware-safety constraints.
- Use concise docstrings where responsibilities or contracts need explanation.
- Identify stages within complicated operations; keep comments accurate when changing code.
- Do not narrate obvious Python syntax. If explanation is extensive because code is too complex, simplify the code.

A developer should understand a complicated section by scanning its comments before reading every statement.

## 6. Testing — Mandatory

**Test contracts, not implementation details.**

- Start with the happy path; then cover important realistic exceptions and hardware-safety failures.
- Test observable inputs, outputs and effects, not every conceivable path or permutation.
- Keep tests few and meaningful: normal operation and realistic failures, without duplicating existing coverage.
- Prefer extending an existing contract test over adding a near-duplicate.
- Tests created solely to diagnose or locate a problem are temporary and must be removed once the problem is understood and fixed.
- Retain a diagnostic test only if it protects a meaningful observable regression, and rewrite it as a contract test where necessary.
- Do not assert logs, private calls, internal queues or signal wiring, and do not change production code solely to satisfy such tests.
- Do not add tests merely for coverage or because a function or branch exists.
- Avoid tests coupled to private methods, mock call counts or incidental internal sequencing. Test protocol ordering where it is part of the observable contract or necessary for hardware safety.
- Use small fixtures and minimal stubs; do not create test frameworks without approval.
- Behaviour-preserving refactors should not require extensive test rewrites.
- If a test fails after a behaviour-preserving change, question whether it tests an implementation detail.
- Run focused tests during development and broader checks at agreed milestones.

Before adding a test, ask: **Which contract or significant real-world risk does this protect?** If unclear, do not add it.

Before completing a task, review all added or modified tests. Remove temporary
diagnostic tests, eliminate redundant coverage, and ensure retained tests verify
observable contracts rather than implementation details.

## 7. Scope and complexity control

- Make the smallest change satisfying the approved requirement. Keep diffs local and reviewable.
- Avoid speculative generalisation and defensive programming for implausible scenarios.
- Functions above roughly 50 lines or modules above roughly 300 lines prompt review, not automatic splitting.
- Do not expand into unrelated improvements. Stop and consult if complexity grows unexpectedly.
- Prefer explicit errors and manual retry over elaborate recovery unless protocol safety requires otherwise.

- Keep MainWindow focused on application-level UI coordination.
- Place feature-specific logic in cohesive components with clear responsibilities.
- Before substantially expanding an existing module, review whether the new behaviour belongs there.
- Avoid both monolithic modules and unnecessary abstraction layers.
- Prefer small, independently testable changes.

**Do not turn a simple requirement into a subsystem.**

## 8. Model choice and token economy

- Use the developer-selected model and reasoning effort. Do not independently escalate.
- If stronger reasoning appears necessary, stop, explain why, recommend a setting and request explicit approval before proceeding.
- Prefer narrowing scope before escalation. Reserve stronger reasoning for approved architecture, difficult protocol questions and complex debugging.
- Use moderate reasoning for straightforward implementation; avoid repeated whole-repository investigations and unnecessary full-suite runs.
- Optimise total development and maintenance cost, not just individual invocation cost.

These instructions cannot override model-selection controls in the Codex environment.

## 9. Git branch workflow

- Never make code changes or commits directly on `main` or `master`.
- Before starting an issue, check the current branch and working-tree status.
- For a new issue, create and switch to a feature branch named `issue/<number>-<short-description>`.
- Create the branch from an up-to-date `main` unless the task explicitly requires a different base.
- If already on the correct feature branch, continue using it.
- If the working tree contains uncommitted changes, do not switch branches or discard changes without approval.
- Do not merge, push, or delete branches unless explicitly instructed.
- Leave completed work uncommitted for review unless explicitly instructed otherwise.

## 10. Change approval and reporting

**Approval is for a bounded task, not each individual edit.** Within an approved task, proceed without repeatedly asking permission. Stop and request approval for architecture changes, new dependencies, significant complexity or scope expansion.

Before nontrivial tasks, explain intended behaviour, design and affected files. Afterwards, summarise implementation, changed files, tests/results, limitations and unexpected complexity.

Do not commit, push, create or modify GitHub issues, or change dependencies without explicit approval.

## 11. Documentation — Mandatory

- Keep `README.md` as the concise entry point for purpose, status, installation, running and links to further guidance.
- Document implemented user workflows as needed; do not present planned features as implemented.
- Keep protocol constraints and hardware-safety reasoning close to relevant code, with references where useful.
- Document API contracts where defined without duplicating clear type hints or docstrings.
- Update user documentation when observable behaviour changes, but do not generate documentation mechanically for every code edit.
- Avoid duplication and remove obsolete explanations.

### Architecture documentation

Maintain `docs/development.md` as a concise guide to major responsibilities, execution flows, component interactions and significant design decisions.

**Think before editing this document.** Ask whether a change materially affects the architecture, adds rationale useful for understanding or maintenance, or makes existing explanations inaccurate. Check whether the information is already explained elsewhere.

Only update it when doing so adds meaningful architectural understanding or corrects an inaccuracy. Do not automatically catalogue new files, classes, functions or routine implementation changes. Prefer refining existing explanations over accumulating sections.

Document non-trivial workflows with concise ASCII diagrams beside relevant
explanations, particularly asynchronous request/response sequences and failure
paths. Keep diagrams synchronised with the implementation.

The document should help the developer understand and modify the application, not inventory its code.

### Hardware independence

CBUS Workbench is a general-purpose CBUS/VLCB management application, not a tool designed for any particular module or manufacturer.

- Implement protocol behaviour according to published CBUS/VLCB specifications, not observations from individual test devices.
- Treat hardware such as CANMIO as test fixtures, never as the basis for general application behaviour.
- Do not hardcode module types, manufacturer IDs, firmware versions, parameter counts or capabilities observed on test hardware.
- Support different modules, firmware versions and implementations, including missing or unsupported features.
- Preserve unknown values rather than inventing defaults.
- Use manufacturer-specific behaviour only when explicitly required, documented and approved.
- Prefer generic, specification-based implementations over device-specific workarounds.
- Test against different module types and edge cases where practical.

## 12. Releases and infrastructure

- Keep packaging and GitHub Actions minimal; prefer built-in GitHub release features.
- Do not build custom issue-to-release tracking, release databases or release-note generators.
- Automate only work that demonstrably benefits from automation.
- Apply the same simplicity rules to scripts, CI and test infrastructure.

## 13. Stop and ask

Stop and consult when requirements are ambiguous, complexity or scope grows, new abstractions/dependencies seem necessary, protocol safety is uncertain, or stronger model/reasoning effort is needed.

**Never interpret uncertainty as permission to invent requirements.**

## Final principle

**Build the smallest understandable application that reliably fulfils its requirements, not the most sophisticated implementation.**
