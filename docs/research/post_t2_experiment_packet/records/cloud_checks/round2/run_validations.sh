#!/bin/bash
# Round-2 validations (ungoverned): traced pilots with the core-consistent telemetry, the model with the
# single-mask probe, the delayed injection and the record-based sidecar validation, and two negative checks.
set -u
S=/tmp/claude-0/-home-user-Shack-Hartmann-AO-Simulation/f1f3bff0-5382-5b19-9652-6c00a445942e/scratchpad
R=/home/user/Shack-Hartmann-AO-Simulation
T=$R/docs/research/post_t2_experiment_packet/tools
PY=$S/env/venv311/bin/python
export PYTHONPATH=$R/src
cd $R
step() { echo "[$(date -u +%FT%TZ)] $*"; }

step "self-test"
$PY $T/linear_loop_noise_model.py --self-test --output $S/round2/model_self_test.json; echo "exit=$?"

step "2 m traced pilot m5 seed 61"
D=$S/round2/ni2m_m5s61; mkdir -p $D
$PY -m shwfs_ao.runtime.resource_guard --label round2_ni2m_m5s61 --estimate-mib 600 --timeout-s 1800 --threads 2 --log $D/guard.log --record $D/guard.json -- \
  $PY $T/timing_pilot_traced_run.py --profile det_emccd_2m_synthetic --profile-version 1 --magnitude 5 --root-seed 61 --frames 200 --burn-in 50 \
  --historical docs/refactor/detector_level_evidence/det09_noise_isolation_2m.json --trace-sidecar $D/trace.npz --output $D/pilot.json > $D/guard_stdout.json 2>&1
echo "exit=$?"
$PY $T/linear_loop_noise_model.py --profile det_emccd_2m_synthetic --profile-version 1 --magnitude 5 --sigma sidecar --sidecar $D/trace.npz --pilot-record $D/pilot.json --output $D/model_sidecar.json; echo "exit=$?"
$PY $T/linear_loop_noise_model.py --profile det_emccd_2m_synthetic --profile-version 1 --magnitude 5 --root-seed 61 --n-steps 200 --burn-in 50 --sigma flat --output $D/model_flat.json; echo "exit=$?"

step "ci-geometry traced pilots (m7, m9; ci damping and 12 m damping) and models"
for mag in 7 9; do for variant in default alpha0p1; do
  D=$S/round2/ci_m${mag}_$variant; mkdir -p $D; extra=""; [ $variant = alpha0p1 ] && extra="--alpha 0.1"
  $PY -m shwfs_ao.runtime.resource_guard --label round2_ci_m${mag}_$variant --estimate-mib 800 --timeout-s 3600 --threads 2 --log $D/guard.log --record $D/guard.json -- \
    $PY $T/timing_pilot_traced_run.py --ci-geometry --magnitude $mag --root-seed 71 --frames 400 --burn-in 100 $extra --trace-sidecar $D/trace.npz --output $D/pilot.json > $D/guard_stdout.json 2>&1
  echo "exit=$? ($mag $variant pilot)"
  $PY $T/linear_loop_noise_model.py --ci-geometry --magnitude $mag $extra --sigma sidecar --sidecar $D/trace.npz --pilot-record $D/pilot.json --output $D/model_sidecar.json; echo "exit=$?"
  $PY $T/linear_loop_noise_model.py --ci-geometry --magnitude $mag $extra --root-seed 71 --n-steps 400 --burn-in 100 --sigma flat --output $D/model_flat.json; echo "exit=$?"
done; done

step "32 series sidecars with --record"
mkdir -p $S/round2/ni2m_models
for f in $S/checks/ni2m_traced/*.npz; do
  b=$(basename $f .npz); lab=${b#det09_noise_isolation_2m_traced__}; m=${lab%%__*}; mag=${m#m}
  $PY $T/linear_loop_noise_model.py --profile det_emccd_2m_synthetic --profile-version 1 --magnitude $mag --sigma sidecar --sidecar $f --record $S/checks/ni2m_traced/det09_noise_isolation_2m_traced.json --output $S/round2/ni2m_models/$lab.json > $S/round2/ni2m_models/$lab.stdout 2>&1 || echo "FAILED $lab: $(tail -1 $S/round2/ni2m_models/$lab.stdout)"
done

step "negative checks: the validation must refuse"
D=$S/round2/negative; mkdir -p $D
# (a) wrong magnitude for the sidecar's label: the configuration hash differs -> refused before any data is read.
$PY $T/linear_loop_noise_model.py --profile det_emccd_2m_synthetic --profile-version 1 --magnitude 6 --sigma sidecar --sidecar $S/round2/ni2m_m5s61/trace.npz --output $D/wrong_magnitude.json > $D/wrong_magnitude.stdout 2>&1; echo "exit=$? (wrong magnitude; expected non-zero)"; tail -1 $D/wrong_magnitude.stdout
# (b) a series sidecar presented with the wrong record row (another seed's record entry): digest mismatch -> refused.
cp $S/checks/ni2m_traced/det09_noise_isolation_2m_traced__m5__seed62.npz $D/det09_noise_isolation_2m_traced__m5__seed61.npz
$PY $T/linear_loop_noise_model.py --profile det_emccd_2m_synthetic --profile-version 1 --magnitude 5 --sigma sidecar --sidecar $D/det09_noise_isolation_2m_traced__m5__seed61.npz --record $S/checks/ni2m_traced/det09_noise_isolation_2m_traced.json --output $D/wrong_record_row.json > $D/wrong_record_row.stdout 2>&1; echo "exit=$? (renamed sidecar against the record; expected non-zero)"; tail -1 $D/wrong_record_row.stdout
# (c) a truncated declared-array table: structural refusal.
$PY - <<'PYEOF'
import json, numpy as np
S="/tmp/claude-0/-home-user-Shack-Hartmann-AO-Simulation/f1f3bff0-5382-5b19-9652-6c00a445942e/scratchpad"
src=f"{S}/round2/ni2m_m5s61/trace.npz"
with np.load(src, allow_pickle=False) as a:
    arrays={k:a[k] for k in a.files if k!="metadata_json"}; meta=json.loads(str(a["metadata_json"]))
arrays["delta_v_m2"]=arrays["delta_v_m2"][:-1]   # one frame short: the declared shape no longer matches
np.savez_compressed(f"{S}/round2/negative/truncated.npz", metadata_json=np.array(json.dumps(meta, sort_keys=True)), **arrays)
PYEOF
$PY $T/linear_loop_noise_model.py --profile det_emccd_2m_synthetic --profile-version 1 --magnitude 5 --sigma sidecar --sidecar $D/truncated.npz --output $D/truncated.json > $D/truncated.stdout 2>&1; echo "exit=$? (truncated series; expected non-zero)"; tail -1 $D/truncated.stdout
step "all done"
