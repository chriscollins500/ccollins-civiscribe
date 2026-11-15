# Development and feedback

CiviScribe has one public native ComfyUI V3 node. Its typed generation record
feeds metadata projections, writers, filenames, sidecars, and display facts.
Development work preserves active-branch selection, exact identity evidence,
pixel quality, private-data handling, and existing-file protection.

## Run the normal checks

Use the repository's locked Python environment and frontend dependencies.
On Windows, invoke tools through Python modules to avoid relocated launchers.

```powershell
.\.venv\Scripts\python.exe -m nox -s python frontend build
```

This checks formatting, lint, strict types, locales, golden fixtures, sidecar
schemas, Python coverage, frontend behavior, and package contents. The Python
coverage gate requires 100 percent statements and branches.

For a release candidate, use the full profile.

```powershell
.\.venv\Scripts\python.exe -m nox -s release
```

It adds process-interruption tests, advisory performance checks, dependency
audits, an SBOM, and license reports. Locked dependencies can be downloaded
during these sessions. Keep system TLS verification enabled.

## Hosted release checks

The release workflow tests the built wheel, source archive, and node packages
across Windows, Linux, and macOS. Linux also uses independent PNG, JPEG, WebP,
and EXIF readers. A separate isolated ComfyUI job checks V3 registration,
serialization, widget visibility, preview sizing, locales, and accessibility.

Performance tests are measurements on the current machine. Coverage and
automated browser results describe the executed checks. Report real uploaded
Civitai parser observations separately when testing catalog recognition.

## Documentation maintenance

The wiki's reviewed Markdown source is versioned in `docs/wiki` in the main
repository. `_Sidebar.md` and `_Footer.md` provide navigation. API examples
live in `docs/examples`. Publish the reviewed pages to the wiki Git repository
and check the rendered links after an update.

The in-node localization files cover English, Arabic, Persian, Spanish,
French, Japanese, Korean, Portuguese (Brazil), Russian, Turkish, Simplified
Chinese, and Traditional Chinese. The wiki is currently written in English.

## Send feedback

Tell us what you were trying to do, how CiviScribe behaved, and what would
make it easier. Feature suggestions and unusual workflow examples help guide
future support. Use Discussions for ideas and questions, or Issues for
reproducible bugs. Comments or private messages on Civitai are also welcome.

Review attachments before sharing so private prompts, paths, or credentials
stay private.
[GitHub Discussions](https://github.com/chriscollins500/ccollins-civiscribe/discussions)
· [GitHub Issues](https://github.com/chriscollins500/ccollins-civiscribe/issues)
· [Contributor guide](https://github.com/chriscollins500/ccollins-civiscribe/blob/main/CONTRIBUTING.md)
