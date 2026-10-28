#!/bin/bash
# Round-1 validations, part 2: models rerun with the finite-window tool; brighter ci-geometry pilots; clean P1 timing.
set -u
S=/tmp/claude-0/-home-user-Shack-Hartmann-AO-Simulation/f1f3bff0-5382-5b19-9652-6c00a445942e/scratchpad
R=/home/user/Shack-Hartmann-AO-Simulation
T=$R/docs/research/post_t2_experiment_packet/tools
PY=$S/env/venv311/bin/python
export PYTHONPATH=$R/src
cd $R
step() { echo "[$(date -u +%FT%TZ)] $*"; }

step "models: rerun with the window tool (old outputs moved to *.v1)"
for D in $S/round1/ni2m_m5s61 $S/round1/ci_m9_default $S/round1/ci_m9_alpha0p1; do
  for f in model_sidecar model_flat; do [ -f $D/$f.json ] && mv $D/$f.json $D/$f.v1.json; done
done
mkdir -p $S/round1/ni2m_models_v1 && mv $S/round1/ni2m_models/*.json $S/round1/ni2m_models_v1/ 2>/dev/null; rm -f $S/round1/ni2m_models/*.stdout
D=$S/round1/ni2m_m5s61
$PY $T/linear_loop_noise_model.py --profile det_emccd_2m_synthetic --profile-version 1 --magnitude 5 --sigma sidecar --sidecar $D/trace.npz --output $D/model_sidecar.json; echo "exit=$?"
$PY $T/linear_loop_noise_model.py --profile det_emccd_2m_synthetic --profile-version 1 --magnitude 5 --root-seed 61 --n-steps 200 --burn-in 50 --sigma flat --output $D/model_flat.json; echo "exit=$?"
for variant in default alpha0p1; do
  D=$S/round1/ci_m9_$variant; extra=""; [ $variant = alpha0p1 ] && extra="--alpha 0.1"
  $PY $T/linear_loop_noise_model.py --ci-geometry --magnitude 9 $extra --sigma sidecar --sidecar $D/trace.npz --output $D/model_sidecar.json; echo "exit=$?"
  $PY $T/linear_loop_noise_model.py --ci-geometry --magnitude 9 $extra --root-seed 71 --n-steps 400 --burn-in 100 --sigma flat --output $D/model_flat.json; echo "exit=$?"
done
step "models: 32 series sidecars"
for f in $S/checks/ni2m_traced/*.npz; do
  b=$(basename $f .npz); lab=${b#det09_noise_isolation_2m_traced__}; m=${lab%%__*}; mag=${m#m}
  $PY $T/linear_loop_noise_model.py --profile det_emccd_2m_synthetic --profile-version 1 --magnitude $mag --sigma sidecar --sidecar $f --output $S/round1/ni2m_models/$lab.json > $S/round1/ni2m_models/$lab.stdout 2>&1 || echo "FAILED $lab: $(tail -1 $S/round1/ni2m_models/$lab.stdout)"
done
step "ci-geometry pilots at m7 (default and alpha 0.1)"
for variant in default alpha0p1; do
  D=$S/round1/ci_m7_$variant; mkdir -p $D; extra=""; [ $variant = alpha0p1 ] && extra="--alpha 0.1"
  $PY -m shwfs_ao.runtime.resource_guard --label round1_ci_m7_$variant --estimate-mib 800 --timeout-s 3600 --threads 2 --log $D/guard.log --record $D/guard.json -- \
    $PY $T/timing_pilot_traced_run.py --ci-geometry --magnitude 7 --root-seed 71 --frames 400 --burn-in 100 $extra --trace-sidecar $D/trace.npz --output $D/pilot.json > $D/guard_stdout.json 2>&1
  echo "exit=$?"; tail -1 $D/guard.log
  $PY $T/linear_loop_noise_model.py --ci-geometry --magnitude 7 $extra --sigma sidecar --sidecar $D/trace.npz --output $D/model_sidecar.json; echo "exit=$?"
  $PY $T/linear_loop_noise_model.py --ci-geometry --magnitude 7 $extra --root-seed 71 --n-steps 400 --burn-in 100 --sigma flat --output $D/model_flat.json; echo "exit=$?"
done
step "P1 ci pilot rerun alone (clean timing)"
D=$S/round1/p1_ci_alone; mkdir -p $D
$PY -m shwfs_ao.runtime.resource_guard --label round1_p1_ci_alone --estimate-mib 400 --timeout-s 1800 --threads 2 --log $D/guard.log --record $D/guard.json -- \
  $PY $T/timing_pilot_fixed_physics.py --scale ci --key ci_baseline_plain_r0 --output $D/pilot.json --scratch-dir $D/scratch > $D/guard_stdout.json 2>&1
echo "exit=$?"; tail -1 $D/guard.log
step "all done"
