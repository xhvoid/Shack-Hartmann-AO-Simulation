# Round-8 reruns: the exact extremes at the corners and edge vertices (2026-10-22)

Review round 8 (on `32470bc`) resolved POST-T2-12 within the declared
linear-model scope, kept POST-T2-20 resolved and left one P2 in
POST-T2-21: the round-7 routine that extremizes each lenslet's 2 x 2
quadratic form over its variance box added a candidate on the null ray of
a singular form, and that candidate set a coordinate to zero whenever the
ray's direction had a zero component, ignoring a positive or fixed
interval on that axis. A supported per-axis fixture with identical
operators then reported a false 48.61 % error range. This directory holds
the reruns of `tools/linear_loop_noise_model.py` (schema
`post_t2_linear_loop_noise_model.v9`) on everything of round 7 plus a
per-axis fixture, each fixture also run with the round-7 tool (`git show
32470bc:docs/research/post_t2_experiment_packet/tools/linear_loop_noise_model.py`).
Nothing governed ran; no runtime code, profile, baseline or historical
record changed.

## The repair (PROTOCOL.md 1.6 (1), 7)

The extremes of a continuous function over a compact box lie at interior
critical points or on the boundary. A homogeneous quadratic's interior
critical points lie on a line through the origin on which it vanishes;
that line meets the box boundary wherever it meets the box, so its value
there is also a boundary value. On each of the four edges the form is a
1-D quadratic whose extremes are the edge's ends or its vertex. The
candidates are therefore the corners and the edge vertices that lie on
their edge; the null-ray candidate is gone, and the routine asserts that
every candidate lies inside both intervals.

## Checks

| Check | Round-7 routine or tool (v8) | Round-8 routine or tool (v9) |
| --- | --- | --- |
| 48 singular forms (rank one, one-sided, zero) on positive, fixed and zero-based intervals against a 401 x 401 grid of the box (`old_routine_check.py`) | 9 wrong, each with a returned point outside an interval; largest deviation 0.98 | 0 wrong; largest deviation 4.4e-16 |
| Self-test: a lenslet with an unused x axis and a fixed y axis | (not in the round-7 self-test) | extremes 0.6 and 0.6, zero width |
| Per-axis fixture: one lenslet's x row outside every operator in every frame while the lenslet stays valid (x interval positive, y fixed at the effective estimate); identical operators throughout | operator error -0.39 %, false extreme range 0.39 % | operator error 1.3e-16, range 0; 50 sampled admissible covariances all at that value |
| Every other record of round 7 (5 round-2 pilots, 3 round-6 pilots with maps, 32 series sidecars, the three round-7 linear fixtures, the round-6 and round-5 fixtures) | as in round 7 | classification, operator error, extremes, budget, ratio and reasons identical on all 50 compared records |
| Negative checks | refused | refused, no record written |
| Acceptance field audit | 66 absolute, 28 relative paths | 66 absolute, 28 relative paths, none missing |

The false range is the y axis's contribution dropped by the out-of-box
candidate, so its size is that lenslet's share of the window: 0.39 % here,
48.61 % in the reviewer's fixture.

## Files

- `run_models.sh`, `run_models.log` (JSON stdout lines stripped); `model_self_test.json`.
- `old_routine_check.py`, `old_routine_check.out`: both routines on the 48 singular cases.
- `{ni2m_m5s61,ci_m7_default,ci_m7_alpha0p1,ci_m9_default,ci_m9_alpha0p1}/model_sidecar.json`; `pilots_maps/<run>/model_sidecar.json`.
- `ni2m_models/<label>__seed<seed>.json` (32) and `summary.json`; `make_summary.py`, `summary.out`.
- `fixtures/`: the fixture builders (`make_linear_fixture.py` now with the `per-axis` variant), the fixture summaries, the v9 and v8 model records and their stdout (the fixture archives stay outside the repository).
- `negative/*.stdout`; `audit_fields.py`, `audit_fields.out`.

The scripts import the packet's tools through `PYTHONPATH=<repo>/src:<repo>/docs/research/post_t2_experiment_packet/tools`.
