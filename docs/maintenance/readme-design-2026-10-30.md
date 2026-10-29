# README redesign record — 2026-10-30

The bilingual landing pages were shortened to make the first successful local
workflow visible before the detailed capability and historical evidence map.
This change reorganizes documentation; it does not change the scientific
acceptance level or claim a new release beyond package version 0.8.0.

## Primary README references

The following upstream project pages were inspected on 2026-10-30. GitHub star
counts are approximate observations from that date, not a quality criterion or
a permanent project metric.

| Project | Observed stars | Organization pattern used |
|---|---:|---|
| [GDSFactory](https://github.com/gdsfactory/gdsfactory) | about 1.1k | State the input/output purpose, then provide a small installation and first-example path before the broader design flow. |
| [Meep](https://github.com/NanoComp/meep) | about 1.8k | Separate the simulator's concrete capabilities from documentation and citation links, making the implemented scope easy to inspect. |
| [Typer](https://github.com/fastapi/typer) | about 20.3k | Put a minimal working example and command usage close to installation, with a clear route into larger applications. |

Only organizational patterns were adapted. No upstream prose, logo, screenshot
or claim of affiliation/endorsement was copied. These projects are references
for documentation structure, not comparative benchmarks of this runtime.

## Resulting information order

1. Concrete purpose, stable project/package/command names and actual CI links.
2. A solver-free MZI quick start using the installable core.
3. Optional native Lumerical installation, plan, run, inspection and export.
4. Real native field images with the 2D and finite-time-window limits visible.
5. Shared versus backend-specific capability table.
6. Numeric recipe reuse, MCP discovery/data tools, paired controls and bounded optimization.
7. Compact documentation map, contribution inputs, licensing and source notes.

The MCP counts reflect the current development registry: 18 tools and 43
resources. Its planning/inspection/export interfaces do not execute a solver.
The native CAD evidence covers three LSF cases and 114 property checks, not
optical simulation of those rendered bends. Cross-solver results are linked to
the dedicated report so a pending refinement cannot turn into a stale README
claim of universal agreement.

## Preservation and image provenance

The former 955-line English and 780-line Chinese READMEs are retained as
[`legacy-readme-en.md`](../legacy-readme-en.md) and
[`legacy-readme-zh.md`](../legacy-readme-zh.md). Their historical showcases,
numerical results and documentation links remain accessible. Links were
adjusted for the new directory, and one former literal local-profile path in
the original prompt example was replaced with a portable skill link. The
archive header explains that historical status counts are not current.

The two gallery PNGs were copied byte-for-byte from native DFT field exports:

| Preview | Bytes | SHA-256 |
|---|---:|---|
| `coupler_field.png` | 413,964 | `58bf69cc716ae900ea39b59861c1e9e583385e4659e3526f79d167ccd9e70cb0` |
| `ring_field.png` | 464,941 | `ace2a0009e2acb76b08de9fad804abbaa527400e60686be7e25b61b020ec00e3` |

See [image provenance](../images/lumerical/README.md) for the actual hashes and
model scope. No image was smoothed, recolored, cropped or regenerated for the
README. The ring's 3 ps window and lack of established resonance/steady-state
convergence remain visible beside the gallery.

The entrypoints contain no local user-profile path or license credential.
Installation and result paths in commands are project-relative or explicit
portable placeholders. Commands assume execution from the repository root.
