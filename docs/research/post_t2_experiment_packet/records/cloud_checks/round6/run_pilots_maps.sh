#!/bin/bash
# Round-6: ci traced pilots re-run with --retain-maps (ungoverned ci geometry) so the model can measure the loop's state directly from the residual maps.
set -u
S=/tmp/claude-0/-home-user-Shack-Hartmann-AO-Simulation/f1f3bff0-5382-5b19-9652-6c00a445942e/scratchpad
R=/home/user/Shack-Hartmann-AO-Simulation
T=$R/docs/research/post_t2_experiment_packet/tools
PY=$S/env/venv311/bin/python
export PYTHONPATH=$R/src
cd $R
step() { echo "[$(date -u +%FT%TZ)] $*"; }
for spec in "7 alpha0p1 --alpha 0.1" "7 default" "9 alpha0p1 --alpha 0.1"; do
  set -- $spec; mag=$1; variant=$2; shift 2; extra="$*"
  D=$S/round6/pilots_maps/ci_m${mag}_$variant; mkdir -p $D
  step "ci m$mag $variant with maps"
  $PY -m shwfs_ao.runtime.resource_guard --label round6_ci_m${mag}_${variant}_maps --estimate-mib 800 --timeout-s 3600 --threads 2 --log $D/guard.log --record $D/guard.json -- \
    $PY $T/timing_pilot_traced_run.py --ci-geometry --magnitude $mag --root-seed 71 --frames 400 --burn-in 100 $extra --retain-maps --trace-sidecar $D/trace.npz --output $D/pilot.json > $D/guard_stdout.json 2>&1
  echo "exit=$?"; ls -la $D/trace.npz 2>/dev/null | awk '{print "sidecar bytes", $5}'
done
step "all done"
