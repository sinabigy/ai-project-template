# 0003: Derive new project instances from protocol-enabled projects (`ai-init --derive`)

- Status: accepted
- Date: 2026-10-05

## Context
Blueprints and forks are themselves initialized projects: they carry tasks, results and state.
A project generated from one needs a fresh instance, without the source's task history, but it
should keep the knowledge that still applies to the inherited code:
- decisions and constraints;
- confirmed validation commands;
- the architecture block.

`ai-init` only initialized *templates*. On an initialized repository it changes nothing, which is
correct for re-runs, so generators had to delete state files by hand. That is a hidden,
inconsistent second state system.

## Decision
Add `ai-init --derive [--name] [--objective] [--origin-name] [--origin-version]`. It runs only on
a copy of an initialized project, and:
- removes `.ai/tasks/*/*.json` and `.ai/context/summaries/*.json`;
- records provenance in `instance.derived_from` and, when an architecture block exists, in
  `architecture.origin`;
- re-runs normal initialization with origin `derived`, which gives a fresh map, STATUS, ROADMAP,
  CURRENT_TASK and the project-discovery task T-0001.

## Alternatives considered
- **Generator-specific cleanup**: rejected. Every generator would reimplement it, and drift
  would break `ai-check`.
- **Keeping the task history**: rejected. Completed tasks describe work on the source, not the new
  project, and they would be confusing as a new project's history.

## Consequences
- Generators call one documented command, and the result passes `ai-check`. Covered by
  `DeriveTests` in the template selftests.

## Reversal conditions
- If derived projects need selected tasks carried over (for example, open follow-ups), add an
  explicit `--keep-task` list rather than changing the default.
