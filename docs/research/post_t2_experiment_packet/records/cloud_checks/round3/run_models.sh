#!/bin/bash
# Round-3: every sidecar model with the effective-operator tool and canonical validation; negative checks for units and axes.
set -u
S=/tmp/claude-0/-home-user-Shack-Hartmann-AO-Simulation/f1f3bff0-5382-5b19-9652-6c00a445942e/scratchpad
R=/home/user/Shack-Hartmann-AO-Simulation
T=$R/docs/research/post_t2_experiment_packet/tools
PY=$S/env/venv311/bin/python
export PYTHONPATH=$R/src
cd $R
step() { echo "[$(date -u +%FT%TZ)] $*"; }
step "self-test"
rm -f $S/round3/model_self_test.json; $PY $T/linear_loop_noise_model.py --self-test --output $S/round3/model_self_test.json; echo "exit=$?"
step "pilot sidecars (round-2 pilots, unchanged) with --pilot-record"
D=$S/round3/ni2m_m5s61; mkdir -p $D
$PY $T/linear_loop_noise_model.py --profile det_emccd_2m_synthetic --profile-version 1 --magnitude 5 --sigma sidecar --sidecar $S/round2/ni2m_m5s61/trace.npz --pilot-record $S/round2/ni2m_m5s61/pilot.json --output $D/model_sidecar.json; echo "exit=$?"
$PY $T/linear_loop_noise_model.py --profile det_emccd_2m_synthetic --profile-version 1 --magnitude 5 --root-seed 61 --n-steps 200 --burn-in 50 --sigma flat --output $D/model_flat.json; echo "exit=$?"
for mag in 7 9; do for variant in default alpha0p1; do
  D=$S/round3/ci_m${mag}_$variant; mkdir -p $D; extra=""; [ $variant = alpha0p1 ] && extra="--alpha 0.1"
  $PY $T/linear_loop_noise_model.py --ci-geometry --magnitude $mag $extra --sigma sidecar --sidecar $S/round2/ci_m${mag}_$variant/trace.npz --pilot-record $S/round2/ci_m${mag}_$variant/pilot.json --output $D/model_sidecar.json; echo "exit=$?"
  $PY $T/linear_loop_noise_model.py --ci-geometry --magnitude $mag $extra --root-seed 71 --n-steps 400 --burn-in 100 --sigma flat --output $D/model_flat.json; echo "exit=$?"
done; done
step "32 series sidecars with --record"
mkdir -p $S/round3/ni2m_models
for f in $S/checks/ni2m_traced/*.npz; do
  b=$(basename $f .npz); lab=${b#det09_noise_isolation_2m_traced__}; m=${lab%%__*}; mag=${m#m}
  $PY $T/linear_loop_noise_model.py --profile det_emccd_2m_synthetic --profile-version 1 --magnitude $mag --sigma sidecar --sidecar $f --record $S/checks/ni2m_traced/det09_noise_isolation_2m_traced.json --output $S/round3/ni2m_models/$lab.json > $S/round3/ni2m_models/$lab.stdout 2>&1 || echo "FAILED $lab: $(tail -1 $S/round3/ni2m_models/$lab.stdout)"
done
step "negative checks: units, axes, dtype"
D=$S/round3/negative; mkdir -p $D
$PY - <<'PYEOF'
import json, numpy as np
S="/tmp/claude-0/-home-user-Shack-Hartmann-AO-Simulation/f1f3bff0-5382-5b19-9652-6c00a445942e/scratchpad"
src=f"{S}/round2/ni2m_m5s61/trace.npz"
with np.load(src, allow_pickle=False) as a:
    arrays={k:a[k] for k in a.files if k!="metadata_json"}; meta=json.loads(str(a["metadata_json"]))
bad_units=json.loads(json.dumps(meta)); bad_units["arrays"]["delta_v_m2"]["units"]="nm2"
np.savez_compressed(f"{S}/round3/negative/wrong_units.npz", metadata_json=np.array(json.dumps(bad_units, sort_keys=True)), **arrays)
bad_axes=json.loads(json.dumps(meta)); bad_axes["arrays"]["noise_on__telemetry__centroids_xy_px"]["axes"]=["frame","xy","lenslet"]
np.savez_compressed(f"{S}/round3/negative/wrong_axes.npz", metadata_json=np.array(json.dumps(bad_axes, sort_keys=True)), **arrays)
bad_dtype=dict(arrays); bad_dtype["noise_on__saturation_fraction"]=arrays["noise_on__saturation_fraction"].astype(np.float32)
bd=json.loads(json.dumps(meta)); bd["arrays"]["noise_on__saturation_fraction"]["dtype"]="float32"
np.savez_compressed(f"{S}/round3/negative/wrong_dtype.npz", metadata_json=np.array(json.dumps(bd, sort_keys=True)), **bad_dtype)
PYEOF
for name in wrong_units wrong_axes wrong_dtype; do
  $PY $T/linear_loop_noise_model.py --profile det_emccd_2m_synthetic --profile-version 1 --magnitude 5 --sigma sidecar --sidecar $D/$name.npz --output $D/$name.json > $D/$name.stdout 2>&1; echo "exit=$? ($name; expected non-zero)"; tail -1 $D/$name.stdout
done
step "all done"
