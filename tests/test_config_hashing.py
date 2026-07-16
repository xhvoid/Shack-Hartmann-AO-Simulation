import numpy as np

from config_hashing import stable_array_descriptor


def test_array_descriptor_is_layout_stable_and_content_sensitive():
    values = np.array([[0.0, -0.0], [np.nan, 3.5]], dtype=float)
    equivalent = np.asfortranarray(np.array([[0.0, 0.0], [np.nan, 3.5]], dtype=float))
    changed = values.copy()
    changed[1, 1] = 3.5001

    first = stable_array_descriptor(values)
    second = stable_array_descriptor(equivalent)
    different = stable_array_descriptor(changed)

    assert first == second
    assert first["shape"] == [2, 2]
    assert first["dtype"] == "float64"
    assert len(first["sha256"]) == 64
    assert first["sha256"] != different["sha256"]
