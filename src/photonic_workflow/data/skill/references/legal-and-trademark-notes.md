# Legal, Trademark, and Release Notes

This reference is a practical publication checklist, not legal advice.

## Goals

Reduce risk when publishing this skill project by ensuring it:

- keeps the installable skill and generated project names vendor-neutral; if a repository slug uses a third-party mark for compatibility discovery, treats that use as nominative and pairs it with clear attribution and non-affiliation language
- does not imply affiliation, authorization, sponsorship, or endorsement
- does not redistribute proprietary software, official docs, official examples, screenshots, logos, license files, or vendor-owned datasets
- uses trademarks only to identify compatible third-party software environments
- states that users must supply and comply with their own valid licenses
- avoids publishing local machine paths, user names, license details, model outputs, and private project files

## Naming Rules

Acceptable project-style names:

- `photonic-integrated-circuit-simulation-skill`
- `integrated-photonics-simulation-skill`
- `waveguide-interferometer-skill`

Prefer repository, folder, and skill names that do not incorporate third-party marks. If an existing public repository slug contains a mark for compatibility discovery, do not claim otherwise: document the nominative purpose, include attribution and non-affiliation language, and consider a neutral slug during a separately authorized repository migration.

## Compatibility Wording

Use third-party software names only when necessary for compatibility. Prefer wording like:

```text
compatible with licensed COMSOL&reg; Multiphysics&reg; simulation software installations
```

Include attribution:

```text
COMSOL and COMSOL Multiphysics are registered trademarks of COMSOL AB.
```

Include non-affiliation:

```text
This project is independent and is not affiliated with, endorsed by, sponsored by, or authorized by COMSOL AB.
```

Do not write copy that suggests official certification, endorsement, bundled access, or redistributed functionality.

## Content That Must Not Be Included

Do not include:

- solver installers
- solver binaries
- plugin jars
- license files
- license server names
- access tokens or credentials
- official product logos or brand artwork
- official screenshots
- official example model files
- copied official manual text
- downloaded vendor documentation
- private paper PDFs
- local `.mph` models unless explicitly cleared
- generated logs that reveal local paths or license details
- generated project names that contain third-party marks

Self-authored workflow notes, original scripts, and compatibility instructions are acceptable when they do not copy proprietary materials and do not imply endorsement.

## Public Release Checklist

Before publishing:

- [x] Existing repository slug trademark use is disclosed as nominative compatibility wording and paired with non-affiliation language; the installable skill name remains vendor-neutral.
- [x] `SKILL.md` skill name contains no third-party solver trademark.
- [x] `README.md` includes non-affiliation language.
- [x] `NOTICE.md` includes trademark attribution.
- [x] No logos, screenshots, manuals, official examples, installers, or binaries are included.
- [x] Users are told to provide their own valid licenses.
- [x] MIT license is limited to this repository's original text/scripts.
- [x] Software references are compatibility statements, not endorsement claims.
- [x] Helper scripts require `-SolverRoot` or `PHOTONIC_SOLVER_ROOT` instead of hard-coded local paths.

Run a local scan before pushing. Customize the path patterns to match your machine and keep any real paths or secrets out of committed documentation:

```powershell
rg -n "<custom-sensitive-patterns>|\.mph|\.class|\.log" .
```

Review any matches manually. Some examples such as `C:\Path\To\...` are safe placeholders; real local paths or secrets are not.

## Git Author Hygiene

Public commits should use the real repository owner or a deliberate project identity. Do not publish commits authored by temporary automation names.

Check authors:

```powershell
git log --format="%h | author=%an <%ae> | committer=%cn <%ce> | %s"
```

If a wrong author was pushed, fix it before broad sharing. Prefer a clean rewrite with `--force-with-lease` only when the repository owner understands the effect and the branch has not been collaboratively updated.

## Official Sources Consulted

- COMSOL trademark and brand guidelines: https://www.comsol.com/trademarks
- COMSOL knowledge base guidance on referencing the software in publications: https://www.comsol.com/support/knowledgebase/1223
- COMSOL license option summary, which points users to the applicable license agreements: https://www.comsol.com/products/licensing
