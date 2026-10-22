#!/bin/bash
# Round 8: the v9 tool (box-extreme candidates within both intervals) on every sidecar and fixture, with the round-7 (v8) tool on the fixtures for comparison.
# actual operators, the arm-operator forcing included) with exact extremes over the admissible covariance; every sidecar,
# the round-6 fixtures, three linear re-synthesis fixtures (with the round-6 tool for comparison), negative checks.
set -u
S=/tmp/claude-0/-home-user-Shack-Hartmann-AO-Simulation/f1f3bff0-5382-5b19-9652-6c00a445942e/scratchpad
R=/home/user/Shack-Hartmann-AO-Simulation
T=$R/docs/research/post_t2_experiment_packet/tools
PY=$S/env/venv311/bin/python
V8=$S/round8/tool_v8.py
export PYTHONPATH=$R/src:$T
cd $R
step() { echo "[$(date -u +%FT%TZ)] $*"; }
O=$S/round8
step "self-test"
rm -f "$O/model_self_test.json"; $PY $T/linear_loop_noise_model.py --self-test --output $O/model_self_test.json; echo "exit=$?"
step "pilot sidecars (round-2 pilots, unchanged) with --pilot-record"
mkdir -p $O/ni2m_m5s61; rm -f "$O/ni2m_m5s61/model_sidecar.json"
$PY $T/linear_loop_noise_model.py --profile det_emccd_2m_synthetic --profile-version 1 --magnitude 5 --sigma sidecar --sidecar $S/round2/ni2m_m5s61/trace.npz --pilot-record $S/round2/ni2m_m5s61/pilot.json --output $O/ni2m_m5s61/model_sidecar.json; echo "exit=$?"
for mag in 7 9; do for variant in default alpha0p1; do
  D=$O/ci_m${mag}_$variant; mkdir -p $D; rm -f "$D/model_sidecar.json"; extra=""; [ $variant = alpha0p1 ] && extra="--alpha 0.1"
  $PY $T/linear_loop_noise_model.py --ci-geometry --magnitude $mag $extra --sigma sidecar --sidecar $S/round2/ci_m${mag}_$variant/trace.npz --pilot-record $S/round2/ci_m${mag}_$variant/pilot.json --output $D/model_sidecar.json; echo "exit=$?"
done; done
step "ci pilots with retained maps (round-6 pilots, unchanged)"
for spec in "7 alpha0p1 --alpha 0.1" "7 default" "9 alpha0p1 --alpha 0.1"; do
  set -- $spec; mag=$1; variant=$2; shift 2; extra="$*"
  D=$O/pilots_maps/ci_m${mag}_$variant; mkdir -p $D; rm -f "$D/model_sidecar.json"
  $PY $T/linear_loop_noise_model.py --ci-geometry --magnitude $mag $extra --sigma sidecar --sidecar $S/round6/pilots_maps/ci_m${mag}_$variant/trace.npz --pilot-record $S/round6/pilots_maps/ci_m${mag}_$variant/pilot.json --output $D/model_sidecar.json; echo "exit=$?"
done
step "32 series sidecars with --record"
mkdir -p $O/ni2m_models; find $O/ni2m_models -name '*.json' -delete
for f in $S/checks/ni2m_traced/*.npz; do
  b=$(basename $f .npz); lab=${b#det09_noise_isolation_2m_traced__}; m=${lab%%__*}; mag=${m#m}
  $PY $T/linear_loop_noise_model.py --profile det_emccd_2m_synthetic --profile-version 1 --magnitude $mag --sigma sidecar --sidecar $f --record $S/checks/ni2m_traced/det09_noise_isolation_2m_traced.json --output $O/ni2m_models/$lab.json > $O/ni2m_models/$lab.stdout 2>&1 || echo "FAILED $lab: $(tail -1 $O/ni2m_models/$lab.stdout)"
done
step "fixtures: linear re-synthesis (operator change, operator change quiet, sparse lenslets, per-axis), each with the v9 and the round-7 (v8) tool; the round-6 carried-state and scaled-series fixtures; the round-5 bracket fixture"
F=$O/fixtures; mkdir -p $F
for v in operator-change operator-change-quiet sparse-lenslets per-axis; do
  $PY $F/make_linear_fixture.py $v $S/round2/ci_m7_alpha0p1/trace.npz $F/$v.npz $F/$v.summary.json > /dev/null; echo "exit=$? (built $v)"
  samples=0; [ $v = sparse-lenslets ] && samples=200; [ $v = per-axis ] && samples=50
  for ver in v9 v8; do
    out=$F/${v}__model_${ver}.json; rm -f "$out"
    if [ $ver = v9 ]; then $PY $T/linear_loop_noise_model.py --ci-geometry --magnitude 7 --alpha 0.1 --sigma sidecar --sidecar $F/$v.npz --admissible-samples $samples --output $out > $F/${v}__model_${ver}.stdout 2>&1
    else $PY $V8 --ci-geometry --magnitude 7 --alpha 0.1 --sigma sidecar --sidecar $F/$v.npz --output $out > $F/${v}__model_${ver}.stdout 2>&1; fi
    echo "exit=$? ($v $ver)"
  done
done
$PY $F/make_carried_fixture.py $S/round2/ci_m7_alpha0p1/trace.npz $F/carried_fixture.npz $F/carried_fixture_summary.json > /dev/null; echo "exit=$? (round-6 carried fixture built)"
for ver in v9 v8; do out=$F/carried__model_${ver}.json; rm -f "$out"
  if [ $ver = v9 ]; then tool=$T/linear_loop_noise_model.py; else tool=$V8; fi
  $PY $tool --ci-geometry --magnitude 7 --alpha 0.1 --sigma sidecar --sidecar $F/carried_fixture.npz --output $out > $F/carried__model_${ver}.stdout 2>&1; echo "exit=$? (carried $ver)"; done
rm -f "$F/series_scaled_model.json"; $PY $T/linear_loop_noise_model.py --ci-geometry --magnitude 7 --alpha 0.1 --sigma sidecar --sidecar $S/round6/fixtures/series_scaled.npz --output $F/series_scaled_model.json > $F/series_scaled_model.stdout 2>&1; echo "exit=$? (series-scaled)"
rm -f "$F/bracket_model.json"; $PY $T/linear_loop_noise_model.py --profile det_emccd_2m_synthetic --profile-version 1 --magnitude 5 --sigma sidecar --sidecar $S/round5/bracket_fixture/fixture.npz --output $F/bracket_model.json > $F/bracket_model.stdout 2>&1; echo "exit=$? (round-5 bracket fixture)"
step "negative checks: units, axes, dtype"
N=$O/negative; mkdir -p $N
for name in wrong_units wrong_axes wrong_dtype; do
  rm -f "$N/$name.json"; $PY $T/linear_loop_noise_model.py --profile det_emccd_2m_synthetic --profile-version 1 --magnitude 5 --sigma sidecar --sidecar $S/round5/negative/$name.npz --output $N/$name.json > $N/$name.stdout 2>&1; echo "exit=$? ($name; expected non-zero)"; tail -1 $N/$name.stdout | cut -c1-200
done
step "all done"
