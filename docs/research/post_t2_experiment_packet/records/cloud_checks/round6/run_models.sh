#!/bin/bash
# Round-6: every sidecar model with the telemetry reconstruction of the command difference, the conditional prediction, the per-lenslet bracket and the direct map measurement; the three ci pilots with retained maps; fixtures; negative checks.
set -u
S=/tmp/claude-0/-home-user-Shack-Hartmann-AO-Simulation/f1f3bff0-5382-5b19-9652-6c00a445942e/scratchpad
R=/home/user/Shack-Hartmann-AO-Simulation
T=$R/docs/research/post_t2_experiment_packet/tools
PY=$S/env/venv311/bin/python
export PYTHONPATH=$R/src:$T
cd $R
step() { echo "[$(date -u +%FT%TZ)] $*"; }
step "self-test"
rm -f $S/round6/model_self_test.json; $PY $T/linear_loop_noise_model.py --self-test --output $S/round6/model_self_test.json; echo "exit=$?"
step "pilot sidecars (round-2 pilots, unchanged) with --pilot-record"
rm -f $S/round6/ni2m_m5s61/model_sidecar.json $S/round6/ci_m*/model_sidecar.json $S/round6/pilots_maps/*/model_sidecar.json $S/round6/ni2m_models/*.json $S/round6/negative/*.json
D=$S/round6/ni2m_m5s61; mkdir -p $D
$PY $T/linear_loop_noise_model.py --profile det_emccd_2m_synthetic --profile-version 1 --magnitude 5 --sigma sidecar --sidecar $S/round2/ni2m_m5s61/trace.npz --pilot-record $S/round2/ni2m_m5s61/pilot.json --output $D/model_sidecar.json; echo "exit=$?"
for mag in 7 9; do for variant in default alpha0p1; do
  D=$S/round6/ci_m${mag}_$variant; mkdir -p $D; extra=""; [ $variant = alpha0p1 ] && extra="--alpha 0.1"
  $PY $T/linear_loop_noise_model.py --ci-geometry --magnitude $mag $extra --sigma sidecar --sidecar $S/round2/ci_m${mag}_$variant/trace.npz --pilot-record $S/round2/ci_m${mag}_$variant/pilot.json --output $D/model_sidecar.json; echo "exit=$?"
done; done
step "ci pilots with retained maps (round-6 pilots)"
for spec in "7 alpha0p1 --alpha 0.1" "7 default" "9 alpha0p1 --alpha 0.1"; do
  set -- $spec; mag=$1; variant=$2; shift 2; extra="$*"
  D=$S/round6/pilots_maps/ci_m${mag}_$variant
  $PY $T/linear_loop_noise_model.py --ci-geometry --magnitude $mag $extra --sigma sidecar --sidecar $D/trace.npz --pilot-record $D/pilot.json --output $D/model_sidecar.json; echo "exit=$?"
done
step "32 series sidecars with --record"
mkdir -p $S/round6/ni2m_models
for f in $S/checks/ni2m_traced/*.npz; do
  b=$(basename $f .npz); lab=${b#det09_noise_isolation_2m_traced__}; m=${lab%%__*}; mag=${m#m}
  $PY $T/linear_loop_noise_model.py --profile det_emccd_2m_synthetic --profile-version 1 --magnitude $mag --sigma sidecar --sidecar $f --record $S/checks/ni2m_traced/det09_noise_isolation_2m_traced.json --output $S/round6/ni2m_models/$lab.json > $S/round6/ni2m_models/$lab.stdout 2>&1 || echo "FAILED $lab: $(tail -1 $S/round6/ni2m_models/$lab.stdout)"
done
step "fixtures: covariance bracket (round-5 fixture), carried state (+25 % window variance through the loop), series scaled by 1.25 without telemetry support"
D=$S/round6/fixtures; mkdir -p $D
rm -f $D/bracket_model.json; $PY $T/linear_loop_noise_model.py --profile det_emccd_2m_synthetic --profile-version 1 --magnitude 5 --sigma sidecar --sidecar $S/round5/bracket_fixture/fixture.npz --output $D/bracket_model.json > $D/bracket_model.stdout 2>&1; echo "exit=$? (bracket fixture)"
rm -f $D/carried_fixture.npz $D/carried_fixture_summary.json $D/carried_model.json
$PY $D/make_carried_fixture.py $S/round2/ci_m7_alpha0p1/trace.npz $D/carried_fixture.npz $D/carried_fixture_summary.json; echo "exit=$? (carried fixture built)"
$PY $T/linear_loop_noise_model.py --ci-geometry --magnitude 7 --alpha 0.1 --sigma sidecar --sidecar $D/carried_fixture.npz --output $D/carried_model.json > $D/carried_model.stdout 2>&1; echo "exit=$? (carried fixture)"
rm -f $D/series_scaled.npz $D/series_scaled_model.json
$PY - <<'PYEOF2'
import json, numpy as np
S = "/tmp/claude-0/-home-user-Shack-Hartmann-AO-Simulation/f1f3bff0-5382-5b19-9652-6c00a445942e/scratchpad"
src = f"{S}/round6/pilots_maps/ci_m7_alpha0p1/trace.npz"
with np.load(src, allow_pickle=False) as a:
    arrays = {k: a[k] for k in a.files if k != "metadata_json"}; meta = json.loads(str(a["metadata_json"]))
arrays["delta_v_m2"] = arrays["delta_v_m2"] * 1.25
arrays["mean_square_difference_m2"] = arrays["cross_term_m2"] + arrays["delta_v_m2"]
np.savez_compressed(f"{S}/round6/fixtures/series_scaled.npz", metadata_json=np.array(json.dumps(meta, sort_keys=True)), **arrays)
print("series-scaled fixture written (delta_v_m2 x 1.25, mean_square_difference_m2 = cross_term_m2 + delta_v_m2; centroids, masks and maps unchanged)")
PYEOF2
$PY $T/linear_loop_noise_model.py --ci-geometry --magnitude 7 --alpha 0.1 --sigma sidecar --sidecar $D/series_scaled.npz --output $D/series_scaled_model.json > $D/series_scaled_model.stdout 2>&1; echo "exit=$? (series-scaled fixture)"
step "replays with logged reconstructor and controller calls (ci m9 with the 12 m damping, ci m7 with the ci damping), then the replay check"
(cd $S/round6/replay && rm -f log.npz log_m7d.npz && $PY replay_log.py log.npz --ci-geometry --magnitude 9 --alpha 0.1 > replay_m9.stdout 2>&1; echo "exit=$? (replay ci m9 alpha 0.1)"; $PY replay_log.py log_m7d.npz --ci-geometry --magnitude 7 > replay_m7d.stdout 2>&1; echo "exit=$? (replay ci m7 ci damping)")
$PY $S/round6/replay/replay_check.py > $S/round6/replay/replay_check.stdout 2>&1; echo "exit=$? (replay check)"
step "negative checks: units, axes, dtype"
D=$S/round6/negative; mkdir -p $D
for name in wrong_units wrong_axes wrong_dtype; do
  $PY $T/linear_loop_noise_model.py --profile det_emccd_2m_synthetic --profile-version 1 --magnitude 5 --sigma sidecar --sidecar $S/round5/negative/$name.npz --output $D/$name.json > $D/$name.stdout 2>&1; echo "exit=$? ($name; expected non-zero)"; tail -1 $D/$name.stdout | cut -c1-200
done
step "all done"
