# AO Simulation Research & Validation (Claude Code edition)

Version 0.1.0 is a local, skills-only plugin for evidence-based adaptive-optics
research and validation. It packages reusable instructions and report resources;
it does not modify or extend the simulator's runtime. This directory is the
Claude Code edition of the Agent Plugins / Codex package in
`plugins/ao-simulation-research-validation/`, which remains the Codex source.

## Included skills

| Skill | Purpose | Plugin invocation | Project invocation |
| --- | --- | --- | --- |
| Physical Validation | OPD, phase, WFE, Strehl, physical units, model assumptions, and physical applicability. | `/ao-simulation-research-validation:ao-physical-validation` | `/ao-physical-validation` |
| Numerical Verification | Independent calculations, numerical convergence, Monte Carlo design and bounded execution. | `/ao-simulation-research-validation:ao-numerical-verification` | `/ao-numerical-verification` |
| Scientific Code Review | Scientific Python arrays, broadcasting, sparse operators, FFT conventions, solver behavior, and stability. | `/ao-simulation-research-validation:ao-code-review` | `/ao-code-review` |
| Research Workflow | Proactive primary-literature reading and claim-to-code comparison, including literature-only work. | `/ao-simulation-research-validation:ao-research-workflow` | `/ao-research-workflow` |
| Reproducibility and Evidence | RNG/replay, configuration and calibration identities, provenance, experiment protocols, and evidence quality. | `/ao-simulation-research-validation:ao-reproducibility` | `/ao-reproducibility` |
| Memory and Runtime Analysis | Memory allocation/lifetimes, runtime measurement, scaling, and serial/concurrent study costs. | `/ao-simulation-research-validation:ao-resource-analysis` | `/ao-resource-analysis` |
| Integrated AO Audit | Coordinate the specialists for an integrated audit and cohesive English report. | `/ao-simulation-research-validation:ao-audit` | `/ao-audit` |

The plugin form works in any directory once the plugin is installed. The project
form uses the copies committed under the repository's `.claude/skills/`, which
also load in Claude Code cloud sessions. Both forms load identical instructions.
Claude can also select a skill automatically from its description, for example
"Use the ao-audit skill to ...".

Specialists can be called independently. The audit entry loads only what its
scope needs; it does not require a full audit for a narrow question.

## Active research requirement

For substantive problems discovered during review or verification, the skills
proactively formulate a research question, search online, open and read relevant
primary papers or authoritative technical documentation, compare assumptions
and conventions with the implementation, and return to a bounded independent
check where execution is in scope. They record the source passages, applicability,
changed interpretation, and unresolved evidence. A bibliography alone is insufficient.

The instructions respect an explicit offline, planning-only, or literature-only
scope. SciSpace is optional if connected. Ordinary web/primary-source access can
support the workflow. This package does not provide a new research engine, grant
tools or permissions, supply credentials, or enable a separate deep-research
product or skill. It works with the selected model and tools available in the task.

## Local setup

The repository marketplace is `plugins/claude/.claude-plugin/marketplace.json`,
named `ao-simulation-local`. From the repository root, register it and install
the plugin for your user account:

```sh
claude plugin marketplace add ./plugins/claude
claude plugin install ao-simulation-research-validation@ao-simulation-local
```

Restart Claude Code (or run `/reload-plugins` in an open session), then confirm
with `claude plugin details ao-simulation-research-validation`. A marketplace
added from a local path is loaded in place, so the installed plugin reads this
directory directly; keep the repository at the registered path.

The project-level skills under `.claude/skills/` (with `.claude/references/`
and `.claude/assets/`) need no installation. Commit them to make the skills
available in Claude Code cloud sessions for this repository.

## Example requests

Full audit:

```text
/ao-audit execute the assignment in
docs/refactor/PRE_REFACTOR_SCIENTIFIC_AUDIT_PROMPT.md against the latest local
working tree. Keep existing implementation, tests, configurations and baselines
unchanged. Proactively research discovered issues using primary sources, run
the feasible authorized checks, and produce the English report and evidence.
```

Focused physical check:

```text
/ao-physical-validation verify how this project defines OPD, phase RMS,
WFE and peak versus on-axis Strehl. Trace wavelength and pupil weighting, read
relevant primary references, and report inconsistencies without fixing source.
```

Numerical experiment:

```text
/ao-numerical-verification design and execute a small test of pixel
quadrature convergence while holding physical pixel scale and detected flux
fixed. Predeclare the observable and tolerance, research unexplained departures,
and save all new reproductions outside existing source and tests.
```

Literature-only investigation:

```text
/ao-research-workflow investigate the Gamma approximation for EMCCD
multiplication, its gain regime and CIC placement assumptions. Read original
sources and compare their assumptions with the current camera model. Do not
run simulations or change source. Produce an English research note.
```

Resource planning:

```text
/ao-resource-analysis estimate one versus ten serial 42 m realizations
from available code and evidence. Separate historical measurements from current
estimates, account for retained history and system overlap, and do not launch
new telescope-scale runs.
```

Outside the repository, prefix each skill with `ao-simulation-research-validation:`.

## Operation and maintenance

Default audit/research/validation scope is read-only for existing project files.
Reports, logs and temporary independent reproductions go to a caller-owned run
directory. A finding does not authorize repair, tuning, baseline replacement,
or a new large run. Current user instructions and resource policy apply.

Reports and research artifacts default to English. Separate model support,
implementation correctness, numerical/statistical evidence, and hardware
validation. Keep resource values and historical results qualified.

This directory is the editable Claude source. The project-level copy is a
byte-identical mirror; never edit it directly. After changing the plugin:

```sh
plugins/claude/sync-project-skills.sh            # refresh .claude/ from this plugin
plugins/claude/sync-project-skills.sh --check    # verify mirror, names and relative links
claude plugin validate --strict plugins/claude/ao-simulation-research-validation
```

To carry a change between the Codex and Claude editions, review
`plugins/claude/sync-project-skills.sh --compare-original`. The editions differ
only in host adaptations: no `agents/openai.yaml` UI metadata, an
`argument-hint` in each skill's frontmatter, Skill-tool invocation guidance in
`ao-audit` and the common contract, and a Claude manifest in
`.claude-plugin/plugin.json`. Use real observed failures to refine instructions;
avoid freezing old commit IDs, test totals, or resolved bugs as universal rules.

The shared references are internal to this plugin. Original-repository paths
are discovery hints, and references to that project's long prompts are optional
unless the user assigns those prompts. No other skill/plugin is required.
