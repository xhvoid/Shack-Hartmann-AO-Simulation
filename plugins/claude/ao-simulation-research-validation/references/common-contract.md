# Shared research and validation contract

Use only the requested scope. A focused equation check, paper comparison, or
diff review does not require a whole-project audit. Explain concepts directly
when no repository investigation or artifact is requested.

## Protected state and execution

- Research, review, and validation requests authorize investigation and relevant
  checks, not repairs, refactoring, tuning, baseline acceptance, or publication.
  Explicit implementation requests are separate scope; preserve the user's
  existing authorization without inventing another approval requirement.
- Read current repository instructions and resource policy. Inspect actual
  code and inputs rather than treating old prompts or status logs as commands.
- For execution-backed conclusions, identify the source tree, dirty inputs,
  environment, imported package, dependencies, seeds, and configuration. Match
  provenance effort to the conclusion; reserve whole-tree inventories for
  whole-tree audits.
- Keep existing source, tests, configurations, resources, notebooks, accepted
  baselines, and documentation unchanged during a read-only assignment. Use a
  new caller-owned output directory for reproductions, logs, and reports.
  Redirect caches/build products, or use a faithful isolated copy containing
  relevant dirty and untracked inputs. Do not silently exercise only clean HEAD.
- Record integrity before and after an audit. A clean Git diff alone does not
  prove an initially dirty file was preserved. Do not undo concurrent user edits.
- Proceed with relevant bounded checks within current authorization. Do not
  bypass guards, infer current permission from historical runs, or launch full
  telescope/ensemble studies solely to fill a report table. If a governed run
  needs authorization, prepare its exact inputs and costs and continue other
  work. Save a precise deferred check rather than claiming a pass.
- In the AO Simulation repository, apply its current serial numerical-execution
  and native-thread policy. Parallel code reading or literature research does
  not authorize parallel numerical jobs.

## Evidence and conclusions

Trace consequential claims through:

`definition/equation -> configuration and assumptions -> code -> source -> independent check -> observation -> conclusion`

Keep these finding classes distinct: implementation defect; model discrepancy;
intentional approximation; validation gap; documentation/provenance error;
engineering debt; environment limitation; future capability. A negative
scientific result can be valid evidence. Finding no actionable defects is an
acceptable outcome.

Record inspected versus executed evidence, producing revision/environment,
confidence, and remaining uncertainty. A citation, backend agreement, seeded
replay, or passing regression does not establish instrument/on-sky accuracy.
For defects, provide the supported trigger, current location, independent
expectation, actual result, minimal reproduction, and impact.

## Active research when a problem is found

Literature investigation is part of review and validation, not just an optional
final bibliography. Unless the user explicitly restricts online work, proactively
turn each substantive suspected problem, unexplained result, disputed assumption,
or numerical failure into a focused external research question. Do not wait for
another instruction to search or merely leave "research later" as the next step.

1. Capture the implemented equation/API, units, configuration, observed behavior,
   and uncertainty. Search using that specific issue and relevant method terms.
2. Open and read the relevant original papers, derivations, corrections, instrument
   documents, or official numerical-library documentation. For a pure API/array
   defect, authoritative software documentation can be the relevant literature;
   do not attach unrelated AO papers to create the appearance of research.
3. Compare assumptions, conventions, validity domains, and alternatives. Seek a
   source that could contradict the initial diagnosis, not only confirm it.
4. Return to the actual implementation. Refine the diagnosis and, when validation
   execution is in scope, run a bounded distinguishing check. Research-only or
   planning-only requests do not authorize experiments.
5. Save the question, searches, passages/locators actually read, applicability,
   evidence-supported interpretation, proposed next check, and resolved/unresolved
   status. Stop when the material question is supported or a specific access,
   resource, or evidence boundary is reached. State that boundary explicitly.

Use [ao-research-workflow](../skills/ao-research-workflow/SKILL.md) for substantial
investigations. Shared evidence can support related findings, but each claim
needs an explicit applicability link. Do not claim a finding was literature-
verified when only a search result, abstract, or generated summary was read.

Use [evidence and report fields](evidence-and-reporting.md) when producing an
artifact. Reports and research notes are English unless the user requests
another language; conversational replies may follow the user's language.

## Tools and scope boundaries

Use available local inspection/execution, web search, and primary-source access.
SciSpace or another research connector is optional. This plugin does not install
a connector, provide credentials, grant file/network permissions, select a model,
or activate a separate deep-research product or skill. State actual tool
availability. An unavailable tool is a coverage limit, not a reason to fabricate
evidence.

Load specialist skills only when needed; use local package paths if their names
are not in the active skill list (in Claude Code, the skills available to the
Skill tool). Each specialist is independently usable.
When working in the original project, consult
[project integration](project-integration.md) for entry points and resource
context. Do not apply its historical project details to an unrelated repository.
