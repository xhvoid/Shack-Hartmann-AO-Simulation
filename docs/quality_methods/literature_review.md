# Primary literature review

Build a defensible connection between a scientific claim and the evidence that
supports it. Read [the common contract](common_contract.md) first.
For local code/evidence routes, use [project integration](project_integration.md)
only as needed; rediscover current implementation facts rather than assuming history.

## Choose the requested research scope

- Literature-only: investigate the stated methods or claims. Do not run tests,
  simulations, or change source. Code inspection is optional when relevant and
  authorized, not a prerequisite for a standalone literature question.
- Code-informed research: inspect the narrow implementation and its actual equation,
  selectors, units, domain and existing evidence before formulating source questions.
- Integrated audit: exchange focused research packets with physical/numerical/code
  reviewers, keeping one claim/evidence ledger. Do not turn research into a refactor.
- Preserve requested deliverable, language and location. Default to read-only
  investigation plus the requested research artifacts; fixes need applicable scope.

## Form a claim packet

When another review discovers a substantive problem, take its issue packet
and investigate proactively under the common contract. Return source-supported
interpretations and discriminating checks to that reviewer, rather than merely
adding bibliography entries or waiting for another research request.

Capture the observable/question, implemented or proposed equation, symbol/units
dictionary, assumptions, parameter range, and what conclusion depends on it.
For code-informed work add source identity, exact implementation location,
configuration/backend/version, and known test or saved-result evidence.
If code is unavailable, mark the implementation mapping unverified.

Ask a precise source question: for example whether a multiplication distribution
requires high gain, whether a covariance is conditional on fixed calibration,
or whether a fitting-tail integral uses the same cutoff and PSD convention.
Do not search only for a title that resembles a filename or method label.

## Retrieve and read authoritative evidence

- Prefer original method/validation papers, official project documentation for the
  installed version, official standards, and original observatory source tables.
  A later review can guide discovery but does not replace the cited derivation.
- Literature databases can aid discovery. Follow retrieved papers to their
  original text and inspect the relevant passage. A generated summary, citation
  graph or abstract is not equation verification.
- Use available primary-source search/retrieval as a fallback. If access fails,
  record the missing evidence and continue independent accessible work; do not
  imply that a paid service or a fixed number of papers is required.
- Read the supporting section/equation/table, including definitions and domain.
  Check preprint/published/version differences and relevant corrections when material.
- Distinguish `full text checked`, `relevant passage checked`, `abstract only`,
  `secondary confirmation`, and `inaccessible/unverified`. Bibliographic confirmation
  alone cannot verify a formula, numerical value, or validity range.
- Record author/organization, title, year/version, DOI or stable URL, precise locator,
  access status/date, supported claim, and any qualification. Do not invent locators.

## Verify the bridge back to the model

Translate the source's symbols, units, Fourier/normalization conventions and
boundary conditions before comparing equations. Identify exactly what the code
implements, approximates, omits, or extends. Equal method names are insufficient.
Distinguish a literature method from repository derivations, engineering parameter
choices, direct public inputs, and measured hardware calibration.

For each material claim record: primary evidence; implementation mapping; applicable
domain; independent validation that exists; unresolved uncertainty; confidence.
Where sources disagree, explain the differing assumptions or retain the disagreement.
A source supporting an algorithm does not validate arbitrary synthetic preset values,
and a reproducible computation does not establish on-sky prediction accuracy.

Propose a discriminating analytic check or experiment when literature cannot settle
an implementation question. Execute it only if the user requested such validation
and it fits the active resource policy; literature-only work stops at the proposal.
Do not weaken test tolerances or replace observations with a desired textbook law.

## Deliver and stop

Write the requested synthesis with claim-adjacent source links, useful locators,
implementation references where applicable, and explicit access/validation limits.
Separate established findings, conditional interpretations, hypotheses and open work.
Research until the material claims have adequate evidence or a clear unresolved
status; avoid both a fixed paper quota and indefinite searching for certainty.
Return actionable gaps to the relevant reviewer without making unrequested fixes.
