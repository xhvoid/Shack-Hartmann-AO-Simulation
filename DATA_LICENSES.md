# Third-Party Data Notices

The repository's MIT license covers repository-authored software and
documentation. It does not make an independent license grant for data obtained
from third-party services. The small cached query results below remain
identified by their embedded source URL, access time, and provenance fields.
Users should review the current upstream terms before publishing or
redistributing those files outside this repository.

This notice records provenance and unresolved permission questions; it is not
legal advice and does not claim that a source has granted rights beyond its
published terms.

## Included direct-public-data caches

Repository paths below use the canonical `src/shwfs_ao/resources/` source
layout. Runtime callers may continue to use the compatible logical `data/...`
names and the generated installed `ao_simulation_data` package during its
deprecation window.

| Source | Included files | Official terms and acknowledgement guidance | Repository treatment and redistribution status |
| --- | --- | --- | --- |
| SVO Filter Profile Service (2MASS J/H/Ks) | `src/shwfs_ao/resources/public/svo_2mass_j_direct.csv`, `svo_2mass_h_direct.csv`, `svo_2mass_ks_direct.csv` | [SVO Filter Profile Service](https://svo2.cab.inta-csic.es/theory/fps/index.php?mode=search) publishes the service's requested acknowledgement; the curves also identify the 2MASS source profile. | Small processed query responses are included for offline, reproducible tests. The repository makes no independent license grant for the SVO or underlying 2MASS data. Explicit permission for further redistribution of these cached responses has not been independently verified; retain provenance and check the current source terms before redistributing. |
| IRSA 2MASS All-Sky Point Source Catalog | `src/shwfs_ao/resources/public/target_photometry_2mass_psc_demo_ngs_bright.csv` | [2MASS data-use acknowledgement guidance](https://irsa.ipac.caltech.edu/data/2MASS/docs/releases/second/doc/sec1_8b.html) and the [IRSA 2MASS mission page](https://irsa.ipac.caltech.edu/Missions/2mass.html). | A small cone-query subset is included for offline photometric anchoring. The repository makes no independent license grant for 2MASS catalog data. Preserve the query provenance and follow the current 2MASS acknowledgement and redistribution guidance. |
| MAST Pan-STARRS DR2 | `src/shwfs_ao/resources/public/target_photometry_panstarrs_dr2_demo_ngs_bright.csv` | [MAST data-use policy](https://archive.stsci.edu/publishing/data-use), [mission acknowledgements](https://archive.stsci.edu/publishing/mission-acknowledgements), and [data attributions](https://archive.stsci.edu/publishing/data-attributions). | A small API-query subset is included for offline photometric anchoring. Reuse should retain MAST/Pan-STARRS provenance and apply the current acknowledgement text published by MAST. The repository does not extend or reinterpret MAST's terms. |
| ESO Paranal Ambient Site Monitor (ASM) API | `src/shwfs_ao/resources/public/eso_asm_paranal_20240729_0300_0800_snapshot.json`, `eso_asm_paranal_20240729_0300_0800_timeseries.csv`, and the retained `0900_1000` historical pair | [ESO copyright notice and terms](https://www.eso.org/public/copyright/) and [ESO publication acknowledgement guidance](https://www.eso.org/cms/publication-acknowledgment.html). | Small derived API responses are included to make the demonstrator reproducible offline. The repository makes no independent license grant for ESO data. Explicit permission for further redistribution of the cached ASM values has not been independently verified; retain source URLs/access times and confirm current ESO terms before redistributing. |

## Acknowledgements for publications and derived products

When these caches materially contribute to a publication or released derived
product, use the acknowledgement wording currently requested by each official
source linked above. Also cite the catalog/service and canonical papers already
recorded in each cache's `source_note` and in
`docs/ao_realistic_demo_parameter_source_inventory.md`.

The repository deliberately links to the official, maintained wording instead
of freezing potentially outdated acknowledgement text here.

## Files that are not direct public measurements

Files under `src/shwfs_ao/resources/samples/`,
`src/shwfs_ao/resources/synthetic_presets/`, and
`src/shwfs_ao/resources/reference_metrics/` are repository fixtures or
generated regression references. The profile under
`src/shwfs_ao/resources/literature_profiles/` is explicitly marked
`synthetic_literature_inspired`; it is not a redistributed observatory data
product. Its scientific influences and assumptions remain documented in its
embedded provenance and the parameter-source inventory.

## Unresolved items

- Re-check upstream terms before adding new public caches or publishing a data
  bundle independently of this software repository.
- Obtain explicit clarification from SVO or ESO if a downstream distribution
  requires a positive redistribution-rights determination rather than source
  attribution and linked terms.
- Keep source URLs, query parameters, access timestamps, and provenance fields
  with every redistributed cache or derived table.
