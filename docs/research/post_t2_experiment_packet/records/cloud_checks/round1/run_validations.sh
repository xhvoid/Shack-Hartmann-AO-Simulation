#!/bin/bash
# Round-1 tool validations (ungoverned only): 2 m traced pilot + model, 32 sidecar models, ci-geometry traced pilots + models.
set -u
S=/tmp/claude-0/-home-user-Shack-Hartmann-AO-Simulation/f1f3bff0-5382-5b19-9652-6c00a445942e/scratchpad
R=/home/user/Shack-Hartmann-AO-Simulation
T=$R/docs/research/post_t2_experiment_packet/tools
PY=$S/env/venv311/bin/python
export PYTHONPATH=$R/src
cd $R
step() { echo "[$(date -u +%FT%TZ)] $*"; }

# (a) 2 m traced pilot m5 seed 61 with historical comparison and a pilot sidecar, then the model on that sidecar.
D=$S/round1/ni2m_m5s61; mkdir -p $D
step "a: 2 m traced pilot"
$PY -m shwfs_ao.runtime.resource_guard --label round1_ni2m_m5s61 --estimate-mib 600 --timeout-s 1800 --threads 2 --log $D/guard.log --record $D/guard.json -- \
  $PY $T/timing_pilot_traced_run.py --profile det_emccd_2m_synthetic --profile-version 1 --magnitude 5 --root-seed 61 --frames 200 --burn-in 50 \
  --historical docs/refactor/detector_level_evidence/det09_noise_isolation_2m.json --trace-sidecar $D/trace.npz --output $D/pilot.json > $D/guard_stdout.json 2>&1
echo "exit=$?"; tail -2 $D/guard.log
step "a: model on the pilot sidecar"
$PY $T/linear_loop_noise_model.py --profile det_emccd_2m_synthetic --profile-version 1 --magnitude 5 --sigma sidecar --sidecar $D/trace.npz --output $D/model_sidecar.json; echo "exit=$?"
$PY $T/linear_loop_noise_model.py --profile det_emccd_2m_synthetic --profile-version 1 --magnitude 5 --root-seed 61 --n-steps 200 --sigma flat --output $D/model_flat.json; echo "exit=$?"

# (b) the model on the 32 series sidecars of the earlier cloud check (2 m, m5-m8, seeds 61-68).
D=$S/round1/ni2m_models; mkdir -p $D
step "b: 32 sidecar models"
for f in $S/checks/ni2m_traced/*.npz; do
  b=$(basename $f .npz); lab=${b#det09_noise_isolation_2m_traced__}; m=${lab%%__*}; mag=${m#m}
  $PY $T/linear_loop_noise_model.py --profile det_emccd_2m_synthetic --profile-version 1 --magnitude $mag --sigma sidecar --sidecar $f --output $D/$lab.json > $D/$lab.stdout 2>&1 || echo "FAILED $lab: $(tail -1 $D/$lab.stdout)"
done
step "b: done"

# (c) ci-geometry traced pilot (12 m @3 physics on the 5 m smoke geometry), m9 seed 71, 400/100, then the model.
for variant in default alpha0p1; do
  D=$S/round1/ci_m9_$variant; mkdir -p $D
  extra=""; [ $variant = alpha0p1 ] && extra="--alpha 0.1"
  step "c: ci-geometry traced pilot ($variant)"
  $PY -m shwfs_ao.runtime.resource_guard --label round1_ci_m9_$variant --estimate-mib 800 --timeout-s 3600 --threads 2 --log $D/guard.log --record $D/guard.json -- \
    $PY $T/timing_pilot_traced_run.py --ci-geometry --magnitude 9 --root-seed 71 --frames 400 --burn-in 100 $extra --trace-sidecar $D/trace.npz --output $D/pilot.json > $D/guard_stdout.json 2>&1
  echo "exit=$?"; tail -2 $D/guard.log
  step "c: model ($variant)"
  $PY $T/linear_loop_noise_model.py --ci-geometry --magnitude 9 $extra --sigma sidecar --sidecar $D/trace.npz --output $D/model_sidecar.json; echo "exit=$?"
  $PY $T/linear_loop_noise_model.py --ci-geometry --magnitude 9 $extra --root-seed 71 --n-steps 400 --sigma flat --output $D/model_flat.json; echo "exit=$?"
done
step "all done"
