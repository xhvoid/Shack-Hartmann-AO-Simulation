"""Fetch small public reference-data caches for the detector-level AO extension.

The script intentionally downloads only small, anonymous public products that
can be committed as provenance-bearing reference inputs:

* SVO Filter Profile Service: 2MASS/2MASS.J/H/Ks transmission curves.
* IRSA 2MASS PSC: a small cone query around the demo guide-star field.
* MAST Pan-STARRS DR2: optical g/r/i/z/y photometry around the same field.
* ESO Paranal ASM API: a nighttime seeing/tau0/theta0/turbulence-speed window.

ERA5/CDS products are not fetched here because they require user credentials.
Gaia TAP access is kept out of the default path so failed archive availability
does not block the small reproducibility cache.
"""

from __future__ import annotations

import csv
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import ssl
import statistics
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

from shwfs_ao.io.resources import render_resource_manifest


ROOT = Path(__file__).resolve().parents[1]
EXTERNAL_DIR = ROOT / "data" / "external"
RESOURCE_DIR = ROOT / "src" / "shwfs_ao" / "resources"
PUBLIC_DIR = RESOURCE_DIR / "public"

SVO_FILTERS = {
    "J": {
        "filter_id": "2MASS/2MASS.J",
        "filename": "svo_2mass_j_direct.csv",
        "xml_filename": "svo_2mass_j.xml",
        "source_id": "SVO_2MASS_J_DIRECT_20260622",
    },
    "H": {
        "filter_id": "2MASS/2MASS.H",
        "filename": "svo_2mass_h_direct.csv",
        "xml_filename": "svo_2mass_h.xml",
        "source_id": "SVO_2MASS_H_DIRECT_20260622",
    },
    "Ks": {
        "filter_id": "2MASS/2MASS.Ks",
        "filename": "svo_2mass_ks_direct.csv",
        "xml_filename": "svo_2mass_ks.xml",
        "source_id": "SVO_2MASS_KS_DIRECT_20260622",
    },
}
for spec in SVO_FILTERS.values():
    spec["url"] = "https://svo2.cab.inta-csic.es/theory/fps/fps.php?" + urllib.parse.urlencode({"ID": spec["filter_id"]})

IRSA_2MASS_DEMO_URL = (
    "https://irsa.ipac.caltech.edu/cgi-bin/Gator/nph-query?"
    + urllib.parse.urlencode(
        {
            "catalog": "fp_psc",
            "spatial": "cone",
            "radius": "60",
            "radunits": "arcsec",
            "objstr": "83.6331 -5.3911",
            "outfmt": "1",
        }
    )
)
PANSTARRS_DR2_DEMO_URL = (
    "https://catalogs.mast.stsci.edu/api/v0.1/panstarrs/dr2/mean.csv?"
    + urllib.parse.urlencode(
        {
            "ra": "83.6331",
            "dec": "-5.3911",
            "radius": "0.02",
            "nDetections.gte": "1",
            "pagesize": "20",
            "columns": (
                "[objID,objName,raMean,decMean,nDetections,gMeanPSFMag,rMeanPSFMag,"
                "iMeanPSFMag,zMeanPSFMag,yMeanPSFMag,gMeanPSFMagErr,rMeanPSFMagErr,"
                "iMeanPSFMagErr,zMeanPSFMagErr,yMeanPSFMagErr]"
            ),
        }
    )
)
ESO_ASM_UTC_START = "2024-07-29T03:00:00Z"
ESO_ASM_UTC_END = "2024-07-29T08:00:00Z"
ESO_ASM_LOCAL_TIME_NOTE = "approximately 23:00-04:00 CLT for Chile winter"
ESO_ASM_NIGHT_WINDOW_CLASS = "nighttime"
ESO_ASM_FIELDS = "dimm_paranal-fwhm,mass_paranal-tau0,mass_paranal-tet0,mass_paranal-turb_speed"
ESO_ASM_WINDOW_TAG = "20240729_0300_0800"
ESO_ASM_DEMO_URL = (
    "https://www.eso.org/asm/api/?"
    + urllib.parse.urlencode(
        {
            "from": ESO_ASM_UTC_START,
            "to": ESO_ASM_UTC_END,
            "fields": ESO_ASM_FIELDS,
        }
    )
)


def main() -> None:
    EXTERNAL_DIR.mkdir(parents=True, exist_ok=True)
    PUBLIC_DIR.mkdir(parents=True, exist_ok=True)
    access_time = datetime.now(timezone.utc).replace(microsecond=0).isoformat()

    svo_outputs: list[Path] = []
    for band_name, spec in SVO_FILTERS.items():
        svo_xml = EXTERNAL_DIR / str(spec["xml_filename"])
        fetch_url(str(spec["url"]), svo_xml)
        output_path = PUBLIC_DIR / str(spec["filename"])
        write_svo_csv(
            svo_xml,
            output_path,
            access_time=access_time,
            band_name=band_name,
            filter_id=str(spec["filter_id"]),
            source_id=str(spec["source_id"]),
            url=str(spec["url"]),
        )
        svo_outputs.extend((svo_xml, output_path))

    irsa_tbl = EXTERNAL_DIR / "2mass_psc_demo_ngs_bright.tbl"
    fetch_url(IRSA_2MASS_DEMO_URL, irsa_tbl)
    write_2mass_photometry_csv(
        irsa_tbl,
        PUBLIC_DIR / "target_photometry_2mass_psc_demo_ngs_bright.csv",
        access_time=access_time,
    )

    panstarrs_csv = EXTERNAL_DIR / "panstarrs_dr2_demo_ngs_bright_raw.csv"
    fetch_url(PANSTARRS_DR2_DEMO_URL, panstarrs_csv)
    write_panstarrs_photometry_csv(
        panstarrs_csv,
        PUBLIC_DIR / "target_photometry_panstarrs_dr2_demo_ngs_bright.csv",
        access_time=access_time,
    )

    eso_json = EXTERNAL_DIR / f"eso_asm_paranal_{ESO_ASM_WINDOW_TAG}.json"
    fetch_url(ESO_ASM_DEMO_URL, eso_json)
    write_eso_asm_snapshot_json(
        eso_json,
        PUBLIC_DIR / f"eso_asm_paranal_{ESO_ASM_WINDOW_TAG}_snapshot.json",
        access_time=access_time,
    )
    write_eso_asm_timeseries_csv(
        eso_json,
        PUBLIC_DIR / f"eso_asm_paranal_{ESO_ASM_WINDOW_TAG}_timeseries.csv",
        access_time=access_time,
    )

    manifest_path = RESOURCE_DIR / "resource_manifest.json"
    manifest_path.write_text(render_resource_manifest(RESOURCE_DIR), encoding="utf-8")

    print("Fetched public reference data:")
    for path in svo_outputs:
        print(f"  {path.relative_to(ROOT)}")
    print(f"  {irsa_tbl.relative_to(ROOT)}")
    print(f"  {(PUBLIC_DIR / 'target_photometry_2mass_psc_demo_ngs_bright.csv').relative_to(ROOT)}")
    print(f"  {panstarrs_csv.relative_to(ROOT)}")
    print(f"  {(PUBLIC_DIR / 'target_photometry_panstarrs_dr2_demo_ngs_bright.csv').relative_to(ROOT)}")
    print(f"  {eso_json.relative_to(ROOT)}")
    print(f"  {(PUBLIC_DIR / f'eso_asm_paranal_{ESO_ASM_WINDOW_TAG}_snapshot.json').relative_to(ROOT)}")
    print(f"  {(PUBLIC_DIR / f'eso_asm_paranal_{ESO_ASM_WINDOW_TAG}_timeseries.csv').relative_to(ROOT)}")
    print(f"  {manifest_path.relative_to(ROOT)}")


def fetch_url(url: str, output_path: Path) -> None:
    request = urllib.request.Request(url)
    context = _ssl_context()
    with urllib.request.urlopen(request, timeout=30.0, context=context) as response:
        output_path.write_bytes(response.read())


def _ssl_context() -> ssl.SSLContext | None:
    try:
        import certifi  # type: ignore[import-not-found]
    except Exception:
        return None
    return ssl.create_default_context(cafile=certifi.where())


def write_svo_csv(
    xml_path: Path,
    output_path: Path,
    *,
    access_time: str,
    band_name: str,
    filter_id: str,
    source_id: str,
    url: str,
) -> None:
    tree = ET.parse(xml_path)
    table_rows = tree.getroot().findall(".//TR")
    rows: list[tuple[float, float]] = []
    for table_row in table_rows:
        cells = table_row.findall("TD")
        if len(cells) < 2:
            continue
        wavelength_angstrom = float(cells[0].text)
        transmission = float(cells[1].text)
        rows.append((wavelength_angstrom * 1.0e-10, transmission))
    if len(rows) < 3:
        raise RuntimeError(f"{xml_path}: no SVO transmission rows were parsed.")

    with output_path.open("w", newline="", encoding="utf-8") as handle:
        handle.write(
            f"# Direct public reference output: SVO Filter Profile Service 2MASS {band_name} "
            "curve converted from cached VOTable XML.\n"
        )
        handle.write("# data_kind=svo_filter_curve\n")
        handle.write(f"# filter_id={filter_id}\n")
        handle.write("# source_class=direct_public_data\n")
        handle.write(
            f"# source_note=SVO Filter Profile Service direct download for {filter_id}; "
            "profile reference http://www.ipac.caltech.edu/2mass/releases/allsky/doc/sec6_4a.html#rsr; "
            "2MASS canonical paper DOI 10.1086/498708.\n"
        )
        handle.write(f"# source_id={source_id}\n")
        handle.write(f"# url={url}\n")
        handle.write(f"# access_time={access_time}\n")
        handle.write("# fallback_used=false\n")
        handle.write("# wavelength_unit=m\n")
        handle.write("# transmission_unit=dimensionless\n")
        writer = csv.writer(handle)
        writer.writerow(["wavelength_m", "transmission"])
        writer.writerows(rows)


def write_2mass_photometry_csv(tbl_path: Path, output_path: Path, *, access_time: str) -> None:
    columns: list[str] | None = None
    records: list[dict[str, str]] = []
    for line in tbl_path.read_text(encoding="utf-8").splitlines():
        if line.startswith("|") and "designation" in line and "j_m" in line:
            columns = [cell.strip() for cell in line.strip("|").split("|")]
            continue
        if columns and line and not line.startswith("|") and not line.startswith("\\"):
            values = line.split()
            if len(values) == len(columns):
                records.append(dict(zip(columns, values)))
    if not records:
        raise RuntimeError(f"{tbl_path}: no IRSA 2MASS PSC rows were parsed.")

    records.sort(key=lambda row: float(row["dist"]))
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        handle.write("# Direct public reference output: IRSA 2MASS All-Sky Point Source Catalog cone query near the demo guide-star field.\n")
        handle.write("# data_kind=target_photometry\n")
        handle.write("# source_class=direct_public_data\n")
        handle.write("# source_note=IRSA 2MASS All-Sky Point Source Catalog PSC fp_psc cone query; 2MASS canonical paper DOI 10.1086/498708.\n")
        handle.write("# source_id=IRSA_2MASS_PSC_DEMO_NGS_BRIGHT_20260622\n")
        handle.write(f"# url={IRSA_2MASS_DEMO_URL}\n")
        handle.write(f"# access_time={access_time}\n")
        handle.write("# fallback_used=false\n")
        handle.write("# ra_unit=deg\n")
        handle.write("# dec_unit=deg\n")
        handle.write("# magnitude_unit=mag\n")
        writer = csv.writer(handle)
        writer.writerow(
            [
                "target_id",
                "ra_deg",
                "dec_deg",
                "twomass_j_mag",
                "twomass_h_mag",
                "twomass_ks_mag",
                "twomass_dist_arcsec",
                "twomass_ph_qual",
            ]
        )
        for record in records:
            writer.writerow(
                [
                    "2MASS_" + record["designation"],
                    record["ra"],
                    record["dec"],
                    record["j_m"],
                    record["h_m"],
                    record["k_m"],
                    record["dist"],
                    record["ph_qual"],
                ]
            )


def write_panstarrs_photometry_csv(csv_path: Path, output_path: Path, *, access_time: str) -> None:
    records: list[dict[str, str]] = []
    with csv_path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            magnitudes: dict[str, float] = {}
            for band, column in (
                ("g", "gMeanPSFMag"),
                ("r", "rMeanPSFMag"),
                ("i", "iMeanPSFMag"),
                ("z", "zMeanPSFMag"),
                ("y", "yMeanPSFMag"),
            ):
                value = float(row[column])
                if math.isfinite(value) and -100.0 < value < 90.0:
                    magnitudes[f"panstarrs_{band}_mag"] = value
            if not magnitudes:
                continue
            records.append(
                {
                    "target_id": "PS1_" + row["objID"],
                    "ra_deg": row["raMean"],
                    "dec_deg": row["decMean"],
                    "panstarrs_n_detections": row["nDetections"],
                    **{key: f"{value:.6f}" for key, value in magnitudes.items()},
                }
            )
    if not records:
        raise RuntimeError(f"{csv_path}: no usable Pan-STARRS DR2 photometry rows were parsed.")

    records.sort(
        key=lambda row: (
            float(row.get("panstarrs_g_mag", row.get("panstarrs_r_mag", "99"))),
            -int(float(row.get("panstarrs_n_detections", "0"))),
        )
    )
    fieldnames = [
        "target_id",
        "ra_deg",
        "dec_deg",
        "panstarrs_g_mag",
        "panstarrs_r_mag",
        "panstarrs_i_mag",
        "panstarrs_z_mag",
        "panstarrs_y_mag",
        "panstarrs_n_detections",
    ]
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        handle.write("# Direct public reference output: MAST Pan-STARRS DR2 mean catalog cone query near the demo guide-star field.\n")
        handle.write("# data_kind=target_photometry\n")
        handle.write("# source_class=direct_public_data\n")
        handle.write("# source_note=MAST Pan-STARRS DR2 mean catalog cone query; Pan-STARRS1 Surveys arXiv:1612.05560 and database/data-products arXiv:1612.05243.\n")
        handle.write("# source_id=MAST_PANSTARRS_DR2_MEAN_DEMO_NGS_BRIGHT_20260622\n")
        handle.write(f"# url={PANSTARRS_DR2_DEMO_URL}\n")
        handle.write(f"# access_time={access_time}\n")
        handle.write("# fallback_used=false\n")
        handle.write("# ra_unit=deg\n")
        handle.write("# dec_unit=deg\n")
        handle.write("# magnitude_unit=mag\n")
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for record in records:
            writer.writerow(record)


def write_eso_asm_snapshot_json(json_path: Path, output_path: Path, *, access_time: str) -> None:
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    seeing = _median_asm_series(payload, "dimm_paranal-fwhm")
    tau0 = _median_asm_series(payload, "mass_paranal-tau0")
    theta0 = _median_asm_series(payload, "mass_paranal-tet0")
    turbulence_speed = _median_asm_series(payload, "mass_paranal-turb_speed")
    unix_time_median_ms = statistics.median(float(row[0]) for row in payload["dimm_paranal-fwhm"])
    r0_500_m = 0.98 * 500.0e-9 / (seeing / 206265.0)
    output = {
        "provenance_note": (
            f"Direct public reference output: ESO Paranal ASM {ESO_ASM_UTC_START} to "
            f"{ESO_ASM_UTC_END} median nighttime atmosphere snapshot."
        ),
        "schema_version": "0.2",
        "data_kind": "eso_asm_snapshot",
        "source_class": "direct_public_data",
        "source_note": (
            f"ESO Paranal ASM API direct JSON query over {ESO_ASM_UTC_START} to "
            f"{ESO_ASM_UTC_END}; fields {ESO_ASM_FIELDS}. r0_500_m is derived from "
            "median seeing using Fried DOI 10.1364/JOSA.56.001372."
        ),
        "source_id": f"ESO_ASM_PARANAL_{ESO_ASM_WINDOW_TAG}_MEDIAN",
        "url": ESO_ASM_DEMO_URL,
        "query_url": ESO_ASM_DEMO_URL,
        "utc_start": ESO_ASM_UTC_START,
        "utc_end": ESO_ASM_UTC_END,
        "local_time_note": ESO_ASM_LOCAL_TIME_NOTE,
        "night_window_class": ESO_ASM_NIGHT_WINDOW_CLASS,
        "fields": ESO_ASM_FIELDS.split(","),
        "access_time": access_time,
        "fallback_used": False,
        "units": {
            "unix_time_median_ms": "ms",
            "seeing_arcsec_500nm": "arcsec",
            "r0_500_m": "m",
            "tau0_s": "s",
            "theta0_arcsec": "arcsec",
            "turbulence_speed_ms": "m/s",
            "sample_count": "count",
        },
        "measurements": {
            "unix_time_median_ms": unix_time_median_ms,
            "seeing_arcsec_500nm": seeing,
            "r0_500_m": r0_500_m,
            "tau0_s": tau0,
            "theta0_arcsec": theta0,
            "turbulence_speed_ms": turbulence_speed,
            "sample_count": len(payload["dimm_paranal-fwhm"]),
        },
    }
    output_path.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")


def write_eso_asm_timeseries_csv(json_path: Path, output_path: Path, *, access_time: str) -> None:
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    fields = (
        "dimm_paranal-fwhm",
        "mass_paranal-tau0",
        "mass_paranal-tet0",
        "mass_paranal-turb_speed",
    )
    n_rows = min(len(payload[field]) for field in fields)
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        handle.write("# Direct public reference output: ESO Paranal ASM nighttime time series for the demo atmosphere anchor.\n")
        handle.write("# data_kind=eso_asm_timeseries\n")
        handle.write("# source_class=direct_public_data\n")
        handle.write(
            f"# source_note=ESO Paranal ASM API direct JSON query over {ESO_ASM_UTC_START} to "
            f"{ESO_ASM_UTC_END}; fields {ESO_ASM_FIELDS}.\n"
        )
        handle.write(f"# source_id=ESO_ASM_PARANAL_{ESO_ASM_WINDOW_TAG}_TIMESERIES\n")
        handle.write(f"# url={ESO_ASM_DEMO_URL}\n")
        handle.write(f"# query_url={ESO_ASM_DEMO_URL}\n")
        handle.write(f"# utc_start={ESO_ASM_UTC_START}\n")
        handle.write(f"# utc_end={ESO_ASM_UTC_END}\n")
        handle.write(f"# local_time_note={ESO_ASM_LOCAL_TIME_NOTE}\n")
        handle.write(f"# night_window_class={ESO_ASM_NIGHT_WINDOW_CLASS}\n")
        handle.write(f"# fields={ESO_ASM_FIELDS}\n")
        handle.write(f"# access_time={access_time}\n")
        handle.write("# fallback_used=false\n")
        handle.write("# time_unit=ms_unix\n")
        handle.write("# seeing_unit=arcsec\n")
        handle.write("# tau0_unit=s\n")
        handle.write("# theta0_unit=arcsec\n")
        handle.write("# turbulence_speed_unit=m/s\n")
        writer = csv.writer(handle)
        writer.writerow(
            [
                "unix_time_ms",
                "seeing_arcsec_500nm",
                "tau0_s",
                "theta0_arcsec",
                "turbulence_speed_ms",
            ]
        )
        for index in range(n_rows):
            writer.writerow(
                [
                    payload["dimm_paranal-fwhm"][index][0],
                    payload["dimm_paranal-fwhm"][index][1],
                    payload["mass_paranal-tau0"][index][1],
                    payload["mass_paranal-tet0"][index][1],
                    payload["mass_paranal-turb_speed"][index][1],
                ]
            )


def _median_asm_series(payload: dict[str, list[list[float]]], key: str) -> float:
    values = [float(row[1]) for row in payload[key] if row and row[1] is not None and math.isfinite(float(row[1]))]
    if not values:
        raise RuntimeError(f"ESO ASM field {key!r} has no finite values.")
    return float(statistics.median(values))


if __name__ == "__main__":
    main()
