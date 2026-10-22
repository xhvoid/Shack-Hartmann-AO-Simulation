"""How the covariance-bracket fixture of CHK-5f was made from the round-2 2 m pilot sidecar (not a genuine run).

One lenslet (index 3) is dropped from the noisy arm's effective row mask and from its sensor validity in every
frame but five analysed frames, so its two rows lie outside the modal operator and have five usable frames,
fewer than the ten the tool needs for a covariance estimate of their own: the tool must bracket them.
"""
import json
import numpy as np

source = "<round-2 pilot>/ni2m_m5s61/trace.npz"
with np.load(source, allow_pickle=False) as a:
    arrays = {k: a[k] for k in a.files if k != "metadata_json"}
    meta = json.loads(str(a["metadata_json"]))
frames = arrays["analysed_frame_index"]
masks = arrays["noise_on__measurement_row_masks"].copy()
valid = arrays["noise_on__telemetry__valid_subapertures"].copy()
lenslet = 3
rows = [2 * lenslet, 2 * lenslet + 1]
keep = set(frames[10:15].tolist())
for f in range(masks.shape[0]):
    if f not in keep:
        masks[f, rows] = False
        valid[f, lenslet] = False
arrays["noise_on__measurement_row_masks"] = masks
arrays["noise_on__telemetry__valid_subapertures"] = valid
np.savez_compressed("fixture.npz", metadata_json=np.array(json.dumps(meta, sort_keys=True)), **arrays)
