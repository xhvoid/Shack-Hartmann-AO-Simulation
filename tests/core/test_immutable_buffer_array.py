"""Sharing already-immutable arrays instead of copying them again.

The repository's immutable-copy helpers rebuild arrays on a ``bytes`` buffer
so they can never be made writeable.  Re-copying such an array is pure memory
cost (a second dense DM influence cube at the 2401-actuator HCIPy scale), so
the helpers on that path hand it out unchanged and keep copying everything
else.
"""

from __future__ import annotations

import numpy as np
import pytest

from shwfs_ao.calibration.interaction import _immutable_array
from shwfs_ao.core.types import _immutable_array_copy, is_immutable_buffer_array
from shwfs_ao.dm.model import _readonly_array


def _immutable(values) -> np.ndarray:
    return _immutable_array_copy(np.asarray(values, dtype=float), dtype=float)


class _Subclass(np.ndarray):
    pass


def test_only_bytes_backed_c_contiguous_arrays_of_the_dtype_qualify() -> None:
    immutable = _immutable(np.arange(12.0).reshape(3, 4))
    assert is_immutable_buffer_array(immutable, dtype=float)
    with pytest.raises(ValueError):
        immutable.setflags(write=True)

    writeable = np.arange(12.0).reshape(3, 4)
    frozen_owner = writeable.copy()
    frozen_owner.flags.writeable = False  # an owner could re-enable writes
    assert not is_immutable_buffer_array(writeable, dtype=float)
    assert not is_immutable_buffer_array(frozen_owner, dtype=float)
    assert not is_immutable_buffer_array(immutable.T, dtype=float)
    assert not is_immutable_buffer_array(immutable, dtype=np.float32)
    assert not is_immutable_buffer_array(immutable.tolist(), dtype=float)
    assert not is_immutable_buffer_array(immutable.view(_Subclass), dtype=float)


@pytest.mark.parametrize("helper", (_readonly_array, _immutable_array))
def test_immutable_helpers_share_immutable_inputs_and_copy_the_rest(helper) -> None:
    immutable = _immutable(np.linspace(0.0, 1.0, 10).reshape(2, 5))
    assert helper(immutable, dtype=float) is immutable

    writeable = np.linspace(0.0, 1.0, 10).reshape(2, 5)
    copied = helper(writeable, dtype=float)
    assert copied is not writeable
    assert not np.shares_memory(copied, writeable)
    np.testing.assert_array_equal(copied, writeable)
    with pytest.raises(ValueError):
        copied.setflags(write=True)
    writeable[0, 0] = 99.0
    assert copied[0, 0] == 0.0
