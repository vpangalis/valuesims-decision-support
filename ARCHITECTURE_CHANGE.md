# Architecture Change Notice

## Status
This repository is undergoing a **fundamental architectural refactor**.

## Reason
The project is transitioning to a:
- class-based
- object-centric
- domain-driven architecture

with:
- a single runtime bridge (`bridge.py`)
- strict separation of concerns
- an agentic AI workflow for reasoning over incidents and evidence

## Scope of Change
- Naming conventions will change
- Folder structure will change
- Script-style and functional code will be replaced
- Runtime logic will be encapsulated in classes

## Reference Point
The tag `pre-architecture-refactor` marks the last state
before this transition.

## Guiding Principles
- No runtime logic outside classes
- No side effects on import
- Agents reason but do not mutate data
