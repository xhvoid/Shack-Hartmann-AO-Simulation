# Research and Validation Methods

These guides describe how to assess adaptive-optics models, numerical
implementations and research evidence. Choose the method appropriate to the
question; a focused review does not require a whole-project audit.

| Question | Guide |
| --- | --- |
| Scope, preservation and evidence requirements | [Shared contract](common_contract.md) |
| Integrated scientific and engineering assessment | [Integrated audit](integrated_audit.md) |
| Physical definitions, assumptions and observables | [Physical validation](physical_validation.md) |
| Independent calculations, convergence and uncertainty | [Numerical verification](numerical_verification.md) |
| Array, Fourier and sparse-solver implementation | [Code review](code_review.md) |
| Primary literature and implementation comparison | [Literature review](literature_review.md) |
| Replay, identities and experiment protocols | [Reproducibility](reproducibility.md) |
| Memory, runtime and study costs | [Resource analysis](resource_analysis.md) |
| Repository entry points and execution context | [Project context](project_integration.md) |
| Reporting fields and evidence limits | [Evidence and reporting](evidence_and_reporting.md) |
| Suggested report structure | [Report template](audit_report_template.md) |

Preserve original research records, source identities and accepted numerical
baselines. Distinguish implementation correctness, agreement with a stated
physical model and validation against independent measurements.
