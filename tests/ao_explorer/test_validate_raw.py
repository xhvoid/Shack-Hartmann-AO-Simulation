"""Raw-evidence mode of the explorer validator on synthetic archives in both supported layouts.

No AO trajectory, calibration or simulation runs.  Each fixture writes deterministic arrays in the selected
contract's raw layout -- v1: ``jobs/<job>/<attempt>/movie.npz`` (probe frames 0, 40, 179; 256 OPD levels); v2:
``cases/<case>/<attempt>/frames/*.npy`` (probe frames 0, 200, 999; 255 OPD levels and the transparent exterior
index 255) -- beside a ``mean_psfs.npz`` with the contract's analysis frames.  The maps are deliberately
asymmetric, the pupil mask has a central obstruction and an off-axis notch, every frame differs and carries a
known non-zero piston, so a transposed, vertically reversed, mis-indexed, unmasked or piston-shifted tile cannot
match by accident.  The residual atlas tiles are encoded here pixel by pixel from the declared display rule (the
oracle never calls the validator's or an exporter's mapping routine).

Frame counts and windows are the contracts' own.  The unit fixtures shrink only the spatial size (9 x 9 pupil
maps); the end-to-end fixtures keep the committed site's 52 x 52 tiles and rebind every hash the synthetic raw
archives touch, so the bundle stays structurally valid.  A pass here is software validation of the raw path on
synthetic data; it is not a verification of the historical raw archives.
"""

from __future__ import annotations

import hashlib
import io
import json
import math
from pathlib import Path
import posixpath
import shutil
import subprocess
import sys

import pytest

np = pytest.importorskip("numpy")
Image = pytest.importorskip("PIL.Image")

import validate  # noqa: E402
import web_contract  # noqa: E402


UNIT_SIZE = 9
UNIT_LIMIT_M = 100e-9
COLUMNS = 8  # the atlas column count the fixtures lay tiles out in (the rectangles they record follow it)
STACK = "frames/pre_update_residual_opd_m.npy"


# ---------------------------------------------------------------------------
# Synthetic arrays and the independent oracle


def _mask(size):
    """A circular pupil with a central obstruction and an off-axis notch: not symmetric under a transpose or a flip."""

    centre = (size - 1) / 2
    mask = np.zeros((size, size), dtype=bool)
    for i in range(size):
        for j in range(size):
            r2 = (i - centre) ** 2 + (j - centre) ** 2
            mask[i, j] = (size / 9) ** 2 <= r2 <= (size / 2) ** 2
    row, column, width = round(0.7 * size), round(0.2 * size), max(1, size // 20)
    mask[row:row + width, column:column + 2 * width] = False
    return mask


def _raw_maps(frames, size, mask, limit, offset_m=0.0):
    """Residual OPD (m) for the given frames: asymmetric, different every frame, clipping at both ends of the display
    range, with an offset of 0.6 L + 0.0005 L k (+ ``offset_m``) so every probe frame has its own non-zero pupil mean."""

    k = np.asarray(frames, dtype=float)[:, None, None]
    i = (np.arange(size, dtype=float) / (size - 1))[None, :, None]
    j = (np.arange(size, dtype=float) / (size - 1))[None, None, :]
    shape = 1.4 * limit * np.sin(2.1 * i + 0.9 * j * j + 0.37 * k) + 0.55 * limit * (i - 0.3) * (j + 0.1) * np.cos(0.11 * k) + 0.3 * limit * i ** 3
    values = shape + 0.6 * limit + 0.0005 * limit * k + offset_m
    return np.where(mask[None], values, np.nan)


def _piston(raw, mask):
    """Pupil mean by exact summation over the masked samples."""

    samples = [float(raw[i, j]) for i in range(raw.shape[0]) for j in range(raw.shape[1]) if mask[i, j]]
    return math.fsum(samples) / len(samples)


def _codes(raw, mask, limit, levels):
    """Raster-order tile codes (row 0 is the top, i.e. the last array row: +y up); None outside the pupil."""

    piston = _piston(raw, mask)
    rows, cols = raw.shape
    tile = [[None] * cols for _ in range(rows)]
    for r in range(rows):
        i = rows - 1 - r
        for j in range(cols):
            if mask[i, j]:
                fraction = min(max((float(raw[i, j]) - piston + limit) / (2.0 * limit), 0.0), 1.0)
                tile[r][j] = int(math.floor(fraction * (levels - 1) + 0.5))
    return tile, piston


def _lut(levels):
    """Distinct colours for every display code (the second channel alone is distinct)."""

    return [((7 * k) % 256, 255 - k, (40 + 3 * k) % 256) for k in range(levels)]


def _hex(lut):
    return ["#%02x%02x%02x" % rgb for rgb in lut]


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _file_record(path):
    data = Path(path).read_bytes()
    return {"bytes": len(data), "sha256": _sha(data)}


def _means(shape, seed):
    y = np.linspace(0.0, 1.0, shape[0])[:, None]
    x = np.linspace(0.0, 1.0, shape[1])[None, :]
    mean = np.exp(-((x - 0.47) ** 2 + (y - 0.52) ** 2) * (9.0 + seed)) * (1.0 + 0.01 * x * y)
    return mean / mean.sum()


# ---------------------------------------------------------------------------
# Atlas encoding (the fixture's own writer)


class Atlas:
    """A residual atlas as display codes (v2, palette PNG) or RGBA pixels (v1), with tiles at the contract's positions."""

    def __init__(self, contract, size, lut):
        self.contract, self.size, self.lut = contract, size, lut
        count = contract.display_count
        self.rects = [[(index % COLUMNS) * size, (index // COLUMNS) * size, size, size] for index in range(count)]
        height, width = math.ceil(count / COLUMNS) * size, COLUMNS * size
        self.paletted = contract.opd_exterior_index is not None
        if self.paletted:
            self.canvas = np.zeros((height, width), dtype=np.uint8)
        else:
            self.canvas = np.zeros((height, width, 4), dtype=np.uint8)
        for index in range(count):  # opaque decoy patterns, so reading the wrong tile cannot pass
            for r in range(size):
                for col in range(size):
                    self.put(index, r, col, (index * 13 + r * 5 + col) % (contract.opd_levels - 1))

    def put(self, index, r, col, code):
        x, y, _, _ = self.rects[index]
        if self.paletted:
            self.canvas[y + r, x + col] = self.contract.opd_exterior_index if code is None else code
        elif code is None:
            self.canvas[y + r, x + col] = (*self.lut[0], 0)
        else:
            self.canvas[y + r, x + col] = (*self.lut[code], 255)

    def put_tile(self, index, tile):
        for r, row in enumerate(tile):
            for col, code in enumerate(row):
                self.put(index, r, col, code)

    def tile_block(self, index):
        x, y, w, h = self.rects[index]
        return self.canvas[y:y + h, x:x + w]

    def png(self, transparent=True):
        buffer = io.BytesIO()
        if self.paletted:
            image = Image.frombytes("P", (self.canvas.shape[1], self.canvas.shape[0]), np.ascontiguousarray(self.canvas).tobytes())
            image.putpalette([value for rgb in self.lut for value in rgb] + [128, 128, 128])
            image.save(buffer, format="PNG", **({"transparency": self.contract.opd_exterior_index} if transparent else {}))
        else:
            Image.fromarray(np.ascontiguousarray(self.canvas), mode="RGBA").save(buffer, format="PNG")
        return buffer.getvalue()


# ---------------------------------------------------------------------------
# Unit fixtures: one case, small maps, the validator's raw path called directly


class RawFixture:
    """One synthetic case in ``contract``'s raw layout and the bundle records that point at it."""

    def __init__(self, root, contract):
        self.contract = contract
        self.size, self.limit = UNIT_SIZE, UNIT_LIMIT_M
        self.mask = _mask(self.size)
        self.lut = _lut(contract.opd_levels)
        self.positions = {frame: index for index, frame in enumerate(contract.display_indices)}
        self.site = root / "site"
        self.series = root / "series"
        self.prefix = "cases/baseline"
        if contract.raw_layout == "movie_npz":
            self.attempt = self.series / "jobs" / "case-baseline" / "attempt-01"
        else:
            self.attempt = self.series / "cases" / "baseline" / "attempt-01"
        (self.attempt / "frames" if contract.raw_layout == "frame_stacks" else self.attempt).mkdir(parents=True)
        (self.site / self.prefix).mkdir(parents=True)
        frames = range(contract.frames) if contract.raw_layout == "frame_stacks" else contract.display_indices
        self.maps = {frame: raw for frame, raw in zip(frames, _raw_maps(list(frames), self.size, self.mask, self.limit))}
        if contract.raw_layout == "frame_stacks":
            np.save(self.attempt / STACK, np.stack([self.maps[k] for k in range(contract.frames)]))
            np.save(self.attempt / "frames" / "frame_index.npy", np.arange(contract.frames, dtype=np.int64))
            np.save(self.attempt / "frames" / "time_s.npy", np.arange(contract.frames) * contract.frame_period_s)
        else:
            np.savez(self.attempt / "movie.npz", indices=np.asarray(contract.display_indices, dtype=np.int64),
                     pre_update_residual_opd_m=np.stack([self.maps[k] for k in contract.display_indices]), pupil_mask=self.mask)
        self.means = {"mean_psf_uncorrected": _means((11, 13), 0), "mean_psf_corrected": _means((11, 13), 5)}
        self.write_means()
        self.observation = {"roles": {role: {"parent": {"array_sha256": _sha(np.ascontiguousarray(self.means[f"mean_psf_{role}"]).tobytes())}}
                                      for role in ("uncorrected", "corrected")}}
        self.provenance = {"job_id": "case-baseline", "attempt": "attempt-01", "raw_evidence": {"files": {}}}
        for path in sorted(p for p in self.attempt.rglob("*") if p.is_file()):
            self.rebind(path.relative_to(self.attempt).as_posix())
        self.atlas = Atlas(contract, self.size, self.lut)
        self.pistons = [0.0] * contract.display_count
        for frame in contract.raw_probe_frames:
            tile, piston = _codes(self.maps[frame], self.mask, self.limit, contract.opd_levels)
            self.atlas.put_tile(self.positions[frame], tile)
            self.pistons[self.positions[frame]] = piston * 1e9
        self.png_options = {}

    def write_means(self, **changes):
        arrays = {**self.means, "analysis_frames": np.arange(self.contract.burn_in, self.contract.frames, dtype=np.int64), "pupil_mask": self.mask, **changes}
        np.savez(self.attempt / "mean_psfs.npz", **arrays)

    def rebind(self, relative):
        self.provenance["raw_evidence"]["files"][relative] = _file_record(self.attempt / relative)

    def run(self):
        """The validator's raw path for this case: (passed raw messages, failed raw messages)."""

        atlas_path = self.site / self.prefix / "atlas-residual.png"
        atlas_path.write_bytes(self.atlas.png(**self.png_options))
        checker = validate.Checker(self.site)
        checker.contract = self.contract
        member = {"path": f"{self.prefix}/atlas-residual.png", **_file_record(atlas_path), "media_type": "image/png", "role": "display_atlas"}
        checker.active = validate.Dataset(checker, self.site, {"members": [member]}, "0" * 64, "active")
        bundle = {"case": {"images": {"residual": {"rectangles_xywh": self.atlas.rects, "display_piston_nm": self.pistons}}},
                  "observation": self.observation, "provenance": self.provenance, "prefix": self.prefix}
        display = {"opd": {"lut_rgb_hex": _hex(self.lut[: self.contract.opd_levels]), "limit_m": self.limit}}
        checker.check_raw(self.series, {"baseline": bundle}, display)
        self.areas = checker.areas
        return [message for message in checker.passed if "member " not in message], checker.failures


@pytest.fixture(params=["v1", "v2"])
def raw(request, tmp_path):
    return RawFixture(tmp_path, {"v1": web_contract.V1, "v2": web_contract.V2}[request.param])


def _only(failures, *expected):
    """Every expected reason fails, and nothing else does."""

    for reason in expected:
        assert any(reason in failure for failure in failures), (reason, failures)
    assert len(failures) == len(expected), failures


def test_synthetic_raw_archives_verify_in_both_layouts(raw):
    c = raw.contract
    passed, failures = raw.run()
    assert failures == []
    raw_files = len(raw.provenance["raw_evidence"]["files"])
    assert raw_files == (4 if c.raw_layout == "frame_stacks" else 2)
    # series directory, attempt, file digests, two parent means, analysis frames, stack length / movie indices, mask, 3 x (present, piston, tile)
    assert raw.areas["raw"] == {"passed": 2 + raw_files + 2 + 1 + 1 + 1 + 9, "failed": 0} and len(passed) == raw.areas["raw"]["passed"], passed
    for frame in c.raw_probe_frames:
        assert f"baseline: residual atlas tile at frame {frame} equals the declared {c.opd_levels}-level mapping of the raw map minus its pupil mean (+y up, no other normalization)" in passed
        assert f"baseline: residual display piston at frame {frame} equals the raw pupil mean" in passed
    assert f"baseline: retained mean covers frames {c.burn_in}-{c.last_frame} (not the displayed frames)" in passed
    assert "baseline: raw pupil mask equals the retained mask" in passed
    assert c.raw_probe_frames == ({"v1": (0, 40, 179), "v2": (0, 200, 999)}[c.name])


def test_fixture_is_not_invariant_under_the_orientation_errors_it_guards(raw):
    # The guards only mean something if the fixture distinguishes the alternatives.
    mask, maps = raw.mask, raw.maps
    assert not np.array_equal(mask, mask.T) and not np.array_equal(mask, mask[::-1]) and not np.array_equal(mask, mask[:, ::-1])
    probes = [maps[frame] for frame in raw.contract.raw_probe_frames]
    assert all(not np.allclose(a, b, equal_nan=True) for n, a in enumerate(probes) for b in probes[n + 1:])
    pistons = [_piston(map_, mask) for map_ in probes]
    assert all(abs(p) > 0.1 * raw.limit for p in pistons) and len(set(pistons)) == 3  # far above one display quantum
    tiles = [[code for row in _codes(map_, mask, raw.limit, raw.contract.opd_levels)[0] for code in row if code is not None] for map_ in probes]
    assert all(len(set(codes)) > 20 for codes in tiles)
    assert any(0 in codes for codes in tiles) and any(raw.contract.opd_levels - 1 in codes for codes in tiles)  # clipping at both ends


# Defects of the archives or of the bundle records; each names exactly the raw checks that must fail.


def _alter_mean(raw):
    changed = raw.means["mean_psf_corrected"].copy()
    changed[3, 4] += 1e-12
    raw.write_means(mean_psf_corrected=changed)
    raw.rebind("mean_psfs.npz")
    return ["baseline: corrected observation parent digest equals the retained numeric mean"]


def _alter_mean_digest(raw):
    raw.observation["roles"]["uncorrected"]["parent"]["array_sha256"] = "0" * 64
    return ["baseline: uncorrected observation parent digest equals the retained numeric mean"]


def _shift_analysis_frames(raw):
    c = raw.contract
    raw.write_means(analysis_frames=np.arange(c.burn_in - 1, c.frames - 1, dtype=np.int64))
    raw.rebind("mean_psfs.npz")
    return [f"baseline: retained mean covers frames {c.burn_in}-{c.last_frame}"]


def _swap_probe_frame(raw):
    # The archive holds the next frame's map where the burn-in probe should be.
    c = raw.contract
    frame = c.burn_in
    if c.raw_layout == "frame_stacks":
        stack = np.load(raw.attempt / STACK)
        stack[[frame, frame + 1]] = stack[[frame + 1, frame]]
        np.save(raw.attempt / STACK, stack)
        raw.rebind(STACK)
    else:
        position = c.display_indices.index(frame)
        with np.load(raw.attempt / "movie.npz") as data:
            arrays = {name: np.array(data[name]) for name in data.files}
        arrays["pre_update_residual_opd_m"][[position, position + 1]] = arrays["pre_update_residual_opd_m"][[position + 1, position]]
        np.savez(raw.attempt / "movie.npz", **arrays)
        raw.rebind("movie.npz")
    return [f"baseline: residual display piston at frame {frame} equals", f"baseline: residual atlas tile at frame {frame} equals"]


def _wrong_piston(raw):
    frame = raw.contract.last_frame
    raw.pistons[raw.positions[frame]] += 1e-6
    return [f"baseline: residual display piston at frame {frame} equals the raw pupil mean"]


def _changed_retained_mask(raw):
    mask = raw.mask.copy()
    mask[raw.size // 2, 1] = not mask[raw.size // 2, 1]
    raw.write_means(pupil_mask=mask)
    raw.rebind("mean_psfs.npz")
    return ["baseline: raw pupil mask equals the retained mask"]


def _changed_alpha(raw):
    # One pupil pixel of the last probe tile made transparent (v2: the exterior palette index; v1: alpha 0).
    frame = raw.contract.last_frame
    i, j = next((i, j) for i in range(raw.size) for j in range(raw.size) if raw.mask[i, j])
    raw.atlas.put(raw.positions[frame], raw.size - 1 - i, j, None)
    return [f"baseline: residual atlas tile at frame {frame} equals"]


def _exterior_opaque(raw):
    if raw.atlas.paletted:
        raw.png_options = {"transparent": False}
    else:
        for frame in raw.contract.raw_probe_frames:
            block = raw.atlas.tile_block(raw.positions[frame])
            block[..., 3] = 255
    return [f"baseline: residual atlas tile at frame {frame} equals" for frame in raw.contract.raw_probe_frames]


def _swapped_tiles(raw):
    first = raw.positions[0]
    a, b = raw.atlas.tile_block(first).copy(), raw.atlas.tile_block(first + 1).copy()
    raw.atlas.tile_block(first)[...] = b
    raw.atlas.tile_block(first + 1)[...] = a
    return ["baseline: residual atlas tile at frame 0 equals"]


def _unflipped_tile(raw):
    frame = raw.contract.burn_in
    block = raw.atlas.tile_block(raw.positions[frame])
    block[...] = block[::-1].copy()
    return [f"baseline: residual atlas tile at frame {frame} equals"]


def _transposed_tile(raw):
    frame = raw.contract.burn_in
    block = raw.atlas.tile_block(raw.positions[frame])
    block[...] = np.swapaxes(block, 0, 1).copy()
    return [f"baseline: residual atlas tile at frame {frame} equals"]


def _other_level_count(raw):
    # The burn-in tile quantized with one level more than the contract declares.
    c, frame = raw.contract, raw.contract.burn_in
    tile, _ = _codes(raw.maps[frame], raw.mask, raw.limit, c.opd_levels + 1)
    raw.atlas.put_tile(raw.positions[frame], [[None if code is None else min(code, c.opd_levels - 1) for code in row] for row in tile])
    return [f"baseline: residual atlas tile at frame {frame} equals"]


def _stale_file_digest(raw):
    # v2: one sample of an unprobed frame (500) changes after its digest was recorded; v1: the recorded size is off by one
    # (a changed byte inside the uncompressed .npz would also fail its CRC and make the archive unreadable).
    if raw.contract.raw_layout == "frame_stacks":
        path = raw.attempt / STACK
        data = bytearray(path.read_bytes())
        start = len(data) - raw.size * raw.size * 8 * (raw.contract.frames - 500)
        data[start + 8 * (raw.size * 4 + 1)] ^= 0x01
        path.write_bytes(bytes(data))
        return [f"baseline: raw {STACK} matches its provenance digest"]
    raw.provenance["raw_evidence"]["files"]["movie.npz"]["bytes"] += 1
    return ["baseline: raw movie.npz matches its provenance digest"]


def _recorded_digest_mismatch(raw):
    raw.provenance["raw_evidence"]["files"]["mean_psfs.npz"]["sha256"] = "f" * 64
    return ["baseline: raw mean_psfs.npz matches its provenance digest"]


DEFECTS = [
    ("altered-mean", _alter_mean),
    ("altered-mean-digest", _alter_mean_digest),
    ("shifted-analysis-frames", _shift_analysis_frames),
    ("wrong-probe-frame", _swap_probe_frame),
    ("wrong-piston", _wrong_piston),
    ("changed-retained-mask", _changed_retained_mask),
    ("changed-alpha", _changed_alpha),
    ("opaque-exterior", _exterior_opaque),
    ("swapped-tiles", _swapped_tiles),
    ("unflipped-tile", _unflipped_tile),
    ("transposed-tile", _transposed_tile),
    ("other-level-count", _other_level_count),
    ("stale-file-digest", _stale_file_digest),
    ("recorded-digest-mismatch", _recorded_digest_mismatch),
]


@pytest.mark.parametrize("name,defect", DEFECTS, ids=[item[0] for item in DEFECTS])
def test_raw_defects_are_refused_with_their_reason(raw, name, defect):
    expected = defect(raw)
    _passed, failures = raw.run()
    _only(failures, *expected)


# Missing or malformed inputs: a recorded failure with the reason, never a silent pass or a crash.


def test_missing_attempt_directory_is_a_recorded_failure(raw):
    shutil.rmtree(raw.attempt)
    _passed, failures = raw.run()
    _only(failures, f"baseline: raw attempt directory {raw.attempt} exists ({raw.contract.raw_layout} layout)")


def test_missing_series_directory_is_a_recorded_failure(raw):
    shutil.rmtree(raw.series)
    _passed, failures = raw.run()
    _only(failures, f"raw evidence: series directory {raw.series} exists", "baseline: raw attempt directory")


def test_missing_mean_archive_is_a_recorded_failure(raw):
    (raw.attempt / "mean_psfs.npz").unlink()
    _passed, failures = raw.run()
    _only(failures, "baseline: raw mean_psfs.npz matches its provenance digest", "is readable (FileNotFoundError:")


def test_malformed_mean_archive_is_a_recorded_failure(raw):
    (raw.attempt / "mean_psfs.npz").write_bytes(b"PK\x03\x04 not a zip archive")
    raw.rebind("mean_psfs.npz")
    _passed, failures = raw.run()
    _only(failures, "is readable (BadZipFile:")


def test_mean_archive_without_its_analysis_frames_is_a_recorded_failure(raw):
    with np.load(raw.attempt / "mean_psfs.npz") as data:
        arrays = {name: np.array(data[name]) for name in data.files if name != "analysis_frames"}
    np.savez(raw.attempt / "mean_psfs.npz", **arrays)
    raw.rebind("mean_psfs.npz")
    _passed, failures = raw.run()
    _only(failures, "is readable (KeyError:")


def test_unreadable_atlas_is_a_recorded_failure(raw):
    raw.atlas.png = lambda **_: b"not an image"
    _passed, failures = raw.run()
    _only(failures, "is readable (UnidentifiedImageError:")
    raw.atlas.png = lambda **_: b"\x89PNG\r\n\x1a\n truncated"
    _passed, failures = raw.run()
    _only(failures, "is readable (OSError:")


def test_short_v2_stack_is_refused_without_reading_past_its_end(tmp_path):
    raw = RawFixture(tmp_path, web_contract.V2)
    stack = np.load(raw.attempt / STACK)
    np.save(raw.attempt / STACK, stack[:-1])
    raw.rebind(STACK)
    passed, failures = raw.run()
    _only(failures, "baseline: raw residual stack holds 1000 frames (shape [999, 9, 9])", "baseline: raw residual map of frame 999 is in the archive")
    assert "baseline: residual atlas tile at frame 200 equals the declared 255-level mapping of the raw map minus its pupil mean (+y up, no other normalization)" in passed


def test_v1_movie_without_a_probe_frame_is_refused(tmp_path):
    raw = RawFixture(tmp_path, web_contract.V1)
    with np.load(raw.attempt / "movie.npz") as data:
        arrays = {name: np.array(data[name]) for name in data.files}
    arrays["indices"][-1] = 178  # the last displayed frame is not frame 179
    np.savez(raw.attempt / "movie.npz", **arrays)
    raw.rebind("movie.npz")
    _passed, failures = raw.run()
    _only(failures, "baseline: raw movie indices equal the frozen rule", "baseline: raw residual map of frame 179 is in the archive")


# ---------------------------------------------------------------------------
# End to end: the committed site with synthetic archives for all eight cases, through the API and the command line


def _dumps(value):
    return (json.dumps(value, indent=1, allow_nan=False, ensure_ascii=False) + "\n").encode("utf-8")


def _update_refs(value, target, data, defining_dir=""):
    if isinstance(value, dict):
        href = value.get("href")
        if isinstance(href, str) and set(value) >= {"bytes", "sha256"} and posixpath.normpath(posixpath.join(defining_dir, href)) == target:
            value.update(bytes=len(data), sha256=_sha(data))
        for item in value.values():
            _update_refs(item, target, data, defining_dir)
    elif isinstance(value, list):
        for item in value:
            _update_refs(item, target, data, defining_dir)


def _site(web_dir, tmp_path, contract):
    """What the validator reads, with the dataset of ``contract`` as the active one (v1: the preserved dataset)."""

    if not (web_dir / "data" / "current.json").is_file():
        pytest.skip("no explorer web bundle in this tree")
    site = tmp_path / "site"
    (site / "data").mkdir(parents=True)
    shutil.copy2(web_dir / "index.html", site / "index.html")
    for code in web_dir.glob("code-*"):
        shutil.copytree(code, site / code.name)
    entry = json.loads((web_dir / "data" / "current.json").read_text())
    if contract is web_contract.V1:
        datasets = [p.parent for p in (web_dir / "data").glob("*/manifest.json") if json.loads(p.read_text()).get("schema") == contract.manifest_schema]
        if len(datasets) != 1:
            pytest.skip("the committed site does not preserve exactly one v1 dataset")
        shutil.copytree(datasets[0], site / "data" / datasets[0].name)
        data = (datasets[0] / "manifest.json").read_bytes()
        entry = {"schema": web_contract.ENTRY_SCHEMA, "dataset_id": datasets[0].name, "manifest": f"{datasets[0].name}/manifest.json",
                 "manifest_bytes": len(data), "manifest_sha256": _sha(data), "code_build": entry["code_build"]}
        (site / "data" / "current.json").write_text(json.dumps(entry, indent=1) + "\n")
    else:
        if json.loads((web_dir / "data" / entry["manifest"]).read_text()).get("schema") != contract.manifest_schema:
            pytest.skip("the committed dataset is not a v2 dataset")
        shutil.copytree(web_dir / "data", site / "data", dirs_exist_ok=True)
    return site


def _attach_synthetic_archives(site, series, contract):
    """Write synthetic archives for every case and rebind the provenance, observation, atlas, case, manifest and entry."""

    entry_path = site / "data" / "current.json"
    entry = json.loads(entry_path.read_text())
    manifest_path = site / "data" / entry["manifest"]
    base = manifest_path.parent
    manifest = json.loads(manifest_path.read_text())
    members = {item["path"]: item for item in manifest["members"]}
    display = json.loads((base / "display.json").read_text())
    lut = [tuple(int(h[k:k + 2], 16) for k in (1, 3, 5)) for h in display["opd"]["lut_rgb_hex"]]
    limit = display["opd"]["limit_m"]
    positions = {frame: index for index, frame in enumerate(contract.display_indices)}

    def write_member(relative, data):
        (base / relative).write_bytes(data)
        members[relative].update(bytes=len(data), sha256=_sha(data))
        return data

    for offset, case_id in enumerate(sorted(manifest["cases"])):
        prefix = f"cases/{case_id}"
        case = json.loads((base / prefix / "case.json").read_text())
        provenance = json.loads((base / prefix / "provenance.json").read_text())
        observation = json.loads((base / prefix / "observation.json").read_text())
        size = case["effective_parameters"]["pupil_pixels"]
        mask = _mask(size)
        if contract.raw_layout == "frame_stacks":
            attempt = series / "cases" / case_id / provenance["attempt"]
            (attempt / "frames").mkdir(parents=True)
            frames = list(range(contract.frames))
        else:
            attempt = series / "jobs" / provenance["job_id"] / provenance["attempt"]
            attempt.mkdir(parents=True)
            frames = list(contract.display_indices)
        maps = _raw_maps(frames, size, mask, limit, offset_m=0.017 * limit * offset)
        if contract.raw_layout == "frame_stacks":
            np.save(attempt / STACK, maps)
            np.save(attempt / "frames" / "frame_index.npy", np.arange(contract.frames, dtype=np.int64))
            np.save(attempt / "frames" / "time_s.npy", np.arange(contract.frames) * contract.frame_period_s)
        else:
            np.savez(attempt / "movie.npz", indices=np.asarray(frames, dtype=np.int64), pre_update_residual_opd_m=maps, pupil_mask=mask)
        shape = tuple(observation["roles"]["corrected"]["parent"]["shape"])
        means = {role: _means(shape, offset + (3 if role == "corrected" else 0)) for role in ("uncorrected", "corrected")}
        np.savez(attempt / "mean_psfs.npz", mean_psf_uncorrected=means["uncorrected"], mean_psf_corrected=means["corrected"],
                 analysis_frames=np.arange(contract.burn_in, contract.frames, dtype=np.int64), pupil_mask=mask)
        provenance["raw_evidence"]["files"] = {p.relative_to(attempt).as_posix(): _file_record(p) for p in sorted(attempt.rglob("*")) if p.is_file()}
        for role in ("uncorrected", "corrected"):
            observation["roles"][role]["parent"]["array_sha256"] = _sha(np.ascontiguousarray(means[role]).tobytes())
        residual = case["images"]["residual"]
        atlas_path = base / prefix / posixpath.normpath(residual["atlas"]["href"])
        image = Image.open(atlas_path)
        canvas = np.array(image) if contract.opd_exterior_index is not None else np.array(image.convert("RGBA"))
        for frame in contract.raw_probe_frames:
            tile, piston = _codes(maps[frames.index(frame)], mask, limit, contract.opd_levels)
            x, y, _, _ = residual["rectangles_xywh"][positions[frame]]
            for r, row in enumerate(tile):
                for col, code in enumerate(row):
                    if contract.opd_exterior_index is not None:
                        canvas[y + r, x + col] = contract.opd_exterior_index if code is None else code
                    else:
                        canvas[y + r, x + col] = (*lut[0], 0) if code is None else (*lut[code], 255)
            residual["display_piston_nm"][positions[frame]] = piston * 1e9
        buffer = io.BytesIO()
        if contract.opd_exterior_index is not None:
            png = Image.frombytes("P", (canvas.shape[1], canvas.shape[0]), np.ascontiguousarray(canvas).tobytes())
            png.putpalette([value for rgb in lut for value in rgb] + [128, 128, 128])
            png.save(buffer, format="PNG", transparency=contract.opd_exterior_index)
        else:
            Image.fromarray(np.ascontiguousarray(canvas), mode="RGBA").save(buffer, format="PNG")
        changed = {f"{prefix}/provenance.json": _dumps(provenance), f"{prefix}/observation.json": _dumps(observation),
                   posixpath.normpath(f"{prefix}/{residual['atlas']['href']}"): buffer.getvalue()}
        for relative, data in changed.items():
            write_member(relative, data)
            _update_refs(case, relative, data, prefix)
        case_data = write_member(f"{prefix}/case.json", _dumps(case))
        _update_refs(manifest["cases"], f"{prefix}/case.json", case_data)
    manifest_data = _dumps(manifest)
    manifest_path.write_bytes(manifest_data)
    entry.update(manifest_bytes=len(manifest_data), manifest_sha256=_sha(manifest_data))
    entry_path.write_text(json.dumps(entry, indent=2) + "\n")
    return base


DIGEST_FAILURES = ("size and SHA-256", "resolves to a matching member", "is missing", "unlisted files")


@pytest.mark.parametrize("name", ["v1", "v2"])
def test_end_to_end_raw_mode_on_the_committed_site(web_dir, scripts_dir, tmp_path, name):
    contract = {"v1": web_contract.V1, "v2": web_contract.V2}[name]
    site = _site(web_dir, tmp_path, contract)
    series = tmp_path / "series"
    base = _attach_synthetic_archives(site, series, contract)

    structural = validate.Checker(site).run(series_dir=None, repo_root=None)
    assert structural["valid"], structural["failures"][:5]
    report = validate.Checker(site).run(series_dir=series, repo_root=None)
    assert report["valid"], report["failures"][:5]
    assert report["raw_evidence_checked"] is True and report["raw_evidence_layout"] == contract.raw_layout
    cases = len(json.loads((base / "manifest.json").read_text())["cases"])
    files = 4 if contract.raw_layout == "frame_stacks" else 2  # residual stack, frame index, times and means / movie and means
    # series directory; per case: attempt, file digests, two means, analysis frames, stack length or movie indices, mask, 3 x (present, piston, tile)
    assert cases == 8 and report["checks_by_area"]["raw"] == {"passed": 1 + cases * (1 + files + 2 + 1 + 1 + 1 + 9), "failed": 0}

    # A changed archive byte (not at a probe frame) is found by the digest binding alone.
    victim = series / ("cases/lower-gain/attempt-01/" + STACK if contract.raw_layout == "frame_stacks" else "jobs/case-lower-gain/attempt-01/mean_psfs.npz")
    original = victim.read_bytes()
    data = bytearray(original)
    data[len(data) // 2 + 3] ^= 0x01
    victim.write_bytes(bytes(data))
    refused = validate.Checker(site).run(series_dir=series, repo_root=None)
    assert not refused["valid"] and any(f"lower-gain: raw {victim.relative_to(victim.parents[0 if contract.raw_layout == 'movie_npz' else 1]).as_posix()} matches its provenance digest" in failure
                                        for failure in refused["failures"]), refused["failures"][:5]
    assert all(failure.startswith("lower-gain: raw") for failure in refused["failures"]), refused["failures"][:5]
    assert not [failure for failure in refused["failures"] if any(word in failure for word in DIGEST_FAILURES)]
    victim.write_bytes(original)

    # Command line: exit 0 on the bound archives, 1 with the reason when one is missing.  The v2 site binds its Research
    # Results to their recorded commit; the v1 contract binds them to the working tree (the legacy rule, which fails on the
    # documentation edited since the v1 research commit), so the v1 success path is the API call above.
    command = [sys.executable, "-B", str(scripts_dir / "validate.py"), "--web-dir", str(site), "--series-dir", str(series), "--repo-root", str(web_dir.parents[1])]
    if contract is web_contract.V2:
        completed = subprocess.run(command, capture_output=True, text=True)
        assert completed.returncode == 0, completed.stdout[-2000:] + completed.stderr[-2000:]
        summary = json.loads(completed.stdout)
        assert summary["valid"] is True and summary["raw_evidence_checked"] is True and summary["raw_evidence_layout"] == "frame_stacks"
        assert summary["checks_by_area"]["raw"]["failed"] == 0
    shutil.rmtree(series / ("cases/weaker-turbulence" if contract.raw_layout == "frame_stacks" else "jobs/case-weaker-turbulence"))
    completed = subprocess.run(command, capture_output=True, text=True)
    assert completed.returncode == 1, completed.stdout[-2000:] + completed.stderr[-2000:]
    summary = json.loads(completed.stdout)
    assert summary["valid"] is False and any("weaker-turbulence: raw attempt directory" in failure and contract.raw_layout in failure for failure in summary["failures"])
