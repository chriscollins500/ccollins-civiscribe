"""Build the public, dependency-light Pages site from reviewed project documents."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
from collections import Counter
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import unquote, urlsplit

from markdown_it import MarkdownIt
from markdown_it.token import Token

from tools.audit_paths import scoped_path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "docs/site"
REPOSITORY = "https://github.com/chriscollins500/ccollins-civiscribe"
ORIGIN = "https://chriscollins500.github.io"
BASE = "/ccollins-civiscribe"
CLIENT_ASSETS = ("styles.css", "app.js", "lab-core.js", "theme.js", "favicon.svg")
EXAMPLES = ("checkpoint-api.json", "save-demo-api.json")
GUIDES = {
    "Quick-start": (
        "Your first save",
        "Connect the finished image, keep the friendly defaults, and save with context.",
        "Start here",
    ),
    "Installation-and-updates": (
        "Installation & updates",
        "ComfyUI Manager, manual installation, requirements, and keeping your node current.",
        "Start here",
    ),
    "Settings-reference": (
        "Every setting, explained",
        "Every input, default, range, format control, and advanced identity option.",
        "Start here",
    ),
    "Image-formats": (
        "PNG, JPEG, or WebP?",
        "Compare pixel fidelity, transparency, metadata, workflow reloading, and previews.",
        "Start here",
    ),
    "Filenames-and-folders": (
        "Filenames & folders",
        "Model names, dates, seeds, dimensions, widget tokens, and safe relative folders.",
        "Make it yours",
    ),
    "Counter-examples": (
        "Counters, your way",
        "Place the counter, choose its padding, and keep existing naming when it is absent.",
        "Make it yours",
    ),
    "Prompts-and-overrides": (
        "Prompts & overrides",
        "Capture the final prompt, including LLM, wildcard, switch, and subgraph workflows.",
        "Follow the evidence",
    ),
    "Models-and-resource-identities": (
        "Models & resource credits",
        "Active branches, model families, hashes, AIR identities, and honest unresolved states.",
        "Follow the evidence",
    ),
    "Civitai-lookup-and-hashing": (
        "Lookup & hashing",
        "Choose a hashing mode and understand exactly what optional Civitai lookup sends.",
        "Follow the evidence",
    ),
    "Manual-resource-identities": (
        "Manual identities",
        "Pin verified identities for multiple active resources with the advanced JSON mapping.",
        "Follow the evidence",
    ),
    "Workflow-examples": (
        "Workflow recipes",
        "Single saves, multiple branches, multiple formats, final prompts, and active resources.",
        "Go further",
    ),
    "Metadata-and-sidecars": (
        "Metadata & sidecars",
        "A1111 text, ComfyUI payloads, Civitai manifests, EXIF, and the detailed JSON companion.",
        "Go further",
    ),
    "API-and-MCP": (
        "API & AI agents",
        "Discover the node, preflight metadata, and read native ComfyUI save reports.",
        "Go further",
    ),
    "Privacy-and-saving-safety": (
        "Privacy & saving safety",
        "Local-first operation, safe paths, private data, and the pixels-first fallback ladder.",
        "Trust & support",
    ),
    "Verify-a-release": (
        "Verify a release",
        "Check exact bytes and signed GitHub/Sigstore provenance before using a release archive.",
        "Trust & support",
    ),
    "Troubleshooting": (
        "Something not quite right?",
        "Find help for missing prompts, unresolved models, naming, lookup, and workflow issues.",
        "Trust & support",
    ),
    "Development-and-feedback": (
        "Contribute & say hello",
        "Testing, translations, feedback, ideas, and the best places to ask for help.",
        "Trust & support",
    ),
    "Project-hub": (
        "The project hub",
        "Downloads, roadmap, discussions, support, security, and contribution paths.",
        "Trust & support",
    ),
}
PROJECT_PAGES = {
    "ROADMAP.md": (
        "roadmap",
        "Where CiviScribe goes next",
        "Current priorities, considered ideas, and completed work.",
    ),
    "SUPPORT.md": (
        "support",
        "Let's get you unstuck",
        "Find the right guide, ask a question, or report a reproducible problem.",
    ),
    "SECURITY.md": (
        "security",
        "Trust, privacy & verification",
        "Security boundaries, private reporting, and signed software and website builds.",
    ),
    "CONTRIBUTING.md": (
        "contributing",
        "Make CiviScribe better",
        "Contribute code, documentation, translations, and carefully tested improvements.",
    ),
    "CODE_OF_CONDUCT.md": (
        "community",
        "A welcoming place to create",
        "The community guidelines shared by CiviScribe's project spaces.",
    ),
}
REFERENCES = {
    "dev/engineering_principles.md": (
        "engineering-principles",
        "Our governing engineering principles",
        "Maximum technical ambition, frontier R&D, decision evidence, and demonstrated results.",
    ),
    "api_and_mcp.md": (
        "api-and-mcp",
        "Native API & MCP reference",
        "HTTP routes, bounded preflight, Python examples, native history reports, and MCP tools.",
    ),
    "final_prompt_overrides.md": (
        "final-prompts",
        "Final prompt wiring",
        "Detailed runtime prompt and subgraph patterns for advanced workflows.",
    ),
    "architecture.md": (
        "architecture",
        "Inside CiviScribe",
        "The generation record, projections, identity, save orchestration, and V3 boundary.",
    ),
    "product_contract.md": (
        "product-contract",
        "The product contract",
        "The focused image-output scope and the invariants the project is built to preserve.",
    ),
    "phase9_sidecars.md": (
        "sidecar-contract",
        "The sidecar contract",
        "Deterministic JSON, committed-image facts, privacy, inclusion rules, and failures.",
    ),
    "phase8_image_writers.md": (
        "image-writers",
        "The image-writing contract",
        "PNG, JPEG, and WebP encoding, pixel fidelity, metadata carriers, and verification.",
    ),
    "dev/comfyui_node_coverage_audit.md": (
        "workflow-coverage",
        "Workflow coverage audit",
        "Supported scanner patterns and the boundaries of static workflow interpretation.",
    ),
    "dev/civitai_site_api_alignment.md": (
        "civitai-api",
        "Civitai API alignment",
        "Resource identity evidence, hash algorithms, API contracts, and documented audit limits.",
    ),
}
GROUP_SUMMARIES = {
    "Start here": "From installation to your first image, without a metadata detour.",
    "Make it yours": "A naming system that fits the way you create.",
    "Follow the evidence": "Keep the right prompt and give the right resources credit.",
    "Go further": "Bigger workflows, deeper records, and useful automation.",
    "Trust & support": "Understand the safeguards and find a human-friendly next step.",
}


def _slug(value: str) -> str:
    return re.sub(r"\s+", "-", re.sub(r"[^\w\s-]", "", value.lower())).strip("-")


def public_paths() -> frozenset[str]:
    """Enumerate every file allowed in the public deployment, including the manifest."""
    return (
        frozenset(
            (
                "index.html",
                "guides/index.html",
                "playground/index.html",
                "changelog/index.html",
                "404.html",
                "search-index.json",
                "site-manifest.json",
                "sitemap.xml",
                "robots.txt",
                ".nojekyll",
                "assets/quill.png",
                "assets/quill.webp",
                "assets/social-preview.jpg",
                "examples/save-report.json",
            )
        )
        | frozenset(f"assets/{name}" for name in CLIENT_ASSETS)
        | frozenset(f"examples/{name}" for name in EXAMPLES)
        | frozenset(f"guides/{key.lower()}/index.html" for key in GUIDES)
        | frozenset(f"reference/{value[0]}/index.html" for value in REFERENCES.values())
        | frozenset(f"{value[0]}/index.html" for value in PROJECT_PAGES.values())
    )


def _check_existing_output(output: Path) -> None:
    allowed = public_paths()
    for path in output.rglob("*"):
        if path.is_symlink() or path.is_junction():
            raise ValueError("Site output contains a link or junction.")
        if path.is_file() and path.relative_to(output).as_posix() not in allowed:
            raise ValueError(
                "Site output contains an unexpected file; use a clean build directory."
            )


def _safe_output(output: Path) -> Path:
    try:
        output = scoped_path(ROOT, output, resolve_links=False)
    except ValueError as error:
        raise ValueError("Site output must be a child of the repository.") from error
    if not output.is_relative_to(ROOT) or output == ROOT:
        raise ValueError("Site output must be a child of the repository.")
    relative = output.relative_to(ROOT)
    if relative.parts[0] not in {".tmp", "_site"}:
        raise ValueError("Site output is restricted to .tmp or _site.")
    for path in (output, *output.parents):
        if path == ROOT:
            break
        if path.is_symlink() or path.is_junction():
            raise ValueError("Site output cannot cross a link or junction.")
    resolved = scoped_path(ROOT, output)
    if resolved == ROOT or resolved.relative_to(ROOT).parts[0] not in {".tmp", "_site"}:
        raise ValueError("Site output cannot escape its approved build directory.")
    return resolved


def _read(path: Path) -> str:
    path = scoped_path(ROOT, path, resolve_links=False)
    if path.is_symlink() or path.is_junction() or not path.resolve().is_relative_to(ROOT):
        raise ValueError("Site inputs must be ordinary project files.")
    return path.read_text(encoding="utf-8")


def _template(name: str, values: dict[str, str]) -> str:
    content = _read(SOURCE / name)
    for key, value in values.items():
        content = content.replace("{{" + key + "}}", value)
    return content


def _write(output: Path, name: str, content: str | bytes) -> None:
    path = scoped_path(output, output / name, resolve_links=False)
    if not path.resolve().is_relative_to(output) or path.is_symlink() or path.is_junction():
        raise ValueError("Generated file escaped the site output.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))


def _mapping() -> dict[Path, str]:
    mappings = {ROOT / "docs/wiki/Home.md": "/guides/"}
    mappings.update({ROOT / f"docs/wiki/{key}.md": f"/guides/{key.lower()}/" for key in GUIDES})
    mappings.update(
        {ROOT / f"docs/{key}": f"/reference/{value[0]}/" for key, value in REFERENCES.items()}
    )
    mappings[ROOT / "CHANGELOG.md"] = "/changelog/"
    mappings.update({ROOT / key: f"/{value[0]}/" for key, value in PROJECT_PAGES.items()})
    return {path.resolve(): route for path, route in mappings.items()}


def _link(href: str, source: Path, mappings: dict[Path, str]) -> str:
    parsed = urlsplit(href)
    if f"{parsed.scheme}://{parsed.netloc}" == ORIGIN and (
        parsed.path == BASE or parsed.path.startswith(BASE + "/")
    ):
        site_path = BASE + "/" if parsed.path == BASE else parsed.path
        return (
            site_path
            + (f"?{parsed.query}" if parsed.query else "")
            + (f"#{parsed.fragment}" if parsed.fragment else "")
        )
    wiki_prefix = f"{REPOSITORY}/wiki"
    path: Path | None = None
    if href.split("#", maxsplit=1)[0] == wiki_prefix or href.startswith(f"{wiki_prefix}/"):
        name = (
            unquote(
                parsed.path.removeprefix("/chriscollins500/ccollins-civiscribe/wiki").strip("/")
            )
            or "Home"
        )
        path = ROOT / f"docs/wiki/{name}.md"
    elif href.startswith(f"{REPOSITORY}/blob/main/"):
        path = ROOT / unquote(
            parsed.path.removeprefix("/chriscollins500/ccollins-civiscribe/blob/main/")
        )
    elif not parsed.scheme and not parsed.netloc and parsed.path:
        path = (source.parent / unquote(parsed.path)).resolve()
    if path is None:
        return href
    resolved = path.resolve()
    if resolved in mappings:
        return BASE + mappings[resolved] + (f"#{parsed.fragment}" if parsed.fragment else "")
    if resolved.is_relative_to(ROOT / "docs/examples") and resolved.suffix == ".json":
        return f"{BASE}/examples/{resolved.name}"
    if resolved.is_relative_to(ROOT):
        relative = resolved.relative_to(ROOT).as_posix()
        return f"{REPOSITORY}/blob/main/{relative}" + (
            f"#{parsed.fragment}" if parsed.fragment else ""
        )
    return href


def _render_markdown(source: Path, mappings: dict[Path, str]) -> tuple[str, list[tuple[str, str]]]:
    markdown = MarkdownIt("commonmark", {"html": False}).enable("table").enable("strikethrough")
    tokens = markdown.parse(_read(source))
    if tokens and tokens[0].type == "heading_open" and tokens[0].tag == "h1":
        tokens = tokens[3:]
    headings: list[tuple[str, str]] = []
    counts: Counter[str] = Counter()

    def visit(items: list[Token]) -> None:
        for index, token in enumerate(items):
            if token.type == "heading_open" and index + 1 < len(items):
                title = items[index + 1].content
                slug = _slug(title)
                count = counts[slug]
                counts[slug] += 1
                anchor = f"{slug}-{count}" if count else slug
                token.attrSet("id", anchor)
                if token.tag == "h2":
                    headings.append((anchor, title))
            if token.type == "link_open" and (href := token.attrGet("href")):
                token.attrSet("href", _link(str(href), source, mappings))
            if token.type == "image" and (src := token.attrGet("src")):
                # Public guides use no external image dependency. Keep image links explicit.
                token.attrSet("src", _link(str(src), source, mappings))
            if token.children:
                visit(token.children)

    visit(tokens)
    rendered = markdown.renderer.render(tokens, markdown.options, {})
    rendered = rendered.replace("<pre>", '<pre tabindex="0">')
    rendered = rendered.replace(
        "<table>",
        '<div class="table-scroll" tabindex="0" role="region" '
        'aria-label="Scrollable reference table"><table>',
    ).replace("</table>", "</table></div>")
    return rendered, headings


def _sidebar(current: str) -> str:
    parts = ['<aside class="guide-sidebar"><nav aria-label="Guide topics">']
    group = ""
    for key, (title, _, category) in GUIDES.items():
        if category != group:
            parts.append(f"<h2>{html.escape(category)}</h2>")
            group = category
        route = f"/guides/{key.lower()}/"
        active = ' aria-current="page"' if route == current else ""
        parts.append(f'<a href="{BASE}{route}"{active}>{html.escape(title)}</a>')
    parts.append(
        "<h2>About the project</h2>"
        + "".join(
            f'<a href="{BASE}/{slug}/">{html.escape(title)}</a>'
            for slug, title, _ in PROJECT_PAGES.values()
        )
        + "<h2>Under the hood</h2>"
        f'<a href="{BASE}/reference/engineering-principles/">Engineering principles</a>'
        f'<a href="{BASE}/reference/api-and-mcp/">API reference</a>'
        f'<a href="{BASE}/reference/architecture/">Architecture</a>'
        f'<a href="{BASE}/guides/#under-the-hood">All technical references</a></nav></aside>'
    )
    return "".join(parts)


def _guide(
    source: Path, title: str, description: str, route: str, mappings: dict[Path, str]
) -> str:
    content, headings = _render_markdown(source, mappings)
    toc = "".join(f'<a href="#{anchor}">{html.escape(label)}</a>' for anchor, label in headings)
    source_url = f"{REPOSITORY}/blob/main/{source.relative_to(ROOT).as_posix()}"
    return _template(
        "guide.html",
        {
            "SIDEBAR": _sidebar(route),
            "GUIDE_TITLE": html.escape(title),
            "GUIDE_DESCRIPTION": html.escape(description),
            "GUIDE_CONTENT": content,
            "SOURCE_URL": source_url,
            "TOC": toc,
        },
    )


def _library() -> str:
    sections = []
    for group, summary in GROUP_SUMMARIES.items():
        links = "".join(
            f'<a href="{BASE}/guides/{key.lower()}/"><h3>{html.escape(title)}</h3>'
            f"<p>{html.escape(description)}</p></a>"
            for key, (title, description, category) in GUIDES.items()
            if category == group
        )
        sections.append(
            '<section class="guide-group"><div class="guide-group-intro">'
            f"<h2>{html.escape(group)}</h2><p>{html.escape(summary)}</p></div>"
            f'<div class="guide-group-links">{links}</div></section>'
        )
    technical = "".join(
        f'<a href="{BASE}/reference/{slug}/"><h3>{html.escape(title)}</h3>'
        f"<p>{html.escape(description)}</p></a>"
        for slug, title, description in REFERENCES.values()
    )
    sections.append(
        '<section class="guide-group" id="under-the-hood"><div class="guide-group-intro">'
        "<h2>Under the hood</h2><p>Contracts, implementation details, and examples "
        "for curious creators and developers. Technical audit documents retain "
        "their recorded dates and limits.</p></div>"
        f'<div class="guide-group-links">{technical}</div></section>'
    )
    project_links = "".join(
        f'<a href="{BASE}/{slug}/"><h3>{html.escape(title)}</h3>'
        f"<p>{html.escape(description)}</p></a>"
        for slug, title, description in PROJECT_PAGES.values()
    )
    sections.append(
        '<section class="guide-group" id="about-the-project"><div class="guide-group-intro">'
        "<h2>About the project</h2><p>One shared set of priorities, support routes, "
        "and community agreements.</p></div>"
        f'<div class="guide-group-links">{project_links}</div></section>'
    )
    return _template("library.html", {"SECTIONS": "".join(sections)})


def _copy_assets(output: Path, version: str) -> None:
    for name in CLIENT_ASSETS:
        _write(output, f"assets/{name}", _read(SOURCE / f"assets/{name}"))
    for source, destination in (
        (ROOT / "assets/branding/civiscribe-icon.png", "quill.png"),
        (SOURCE / "assets/quill.webp", "quill.webp"),
        (ROOT / "assets/branding/civiscribe-social-preview.jpg", "social-preview.jpg"),
    ):
        if source.is_symlink() or not source.resolve().is_relative_to(ROOT):
            raise ValueError("Brand asset escaped the repository.")
        _write(output, f"assets/{destination}", source.read_bytes())
    for name in EXAMPLES:
        example = ROOT / "docs/examples" / name
        text = _read(example)
        json.loads(text)
        _write(output, f"examples/{example.name}", text)
    example_report = {
        "schema": "ccollins-civiscribe.save-result",
        "schemaVersion": "1.0.0",
        "version": version,
        "images": [
            {
                "filename": "portrait_00001_.png",
                "subfolder": "",
                "type": "output",
                "format": "png",
                "width": 1024,
                "height": 768,
                "metadataStatus": "complete",
                "sidecarStatus": "not_requested",
                "sidecarFilename": None,
            }
        ],
        "warnings": [],
    }
    _write(output, "examples/save-report.json", json.dumps(example_report, indent=2) + "\n")


def _document_pages(mappings: dict[Path, str]) -> Iterator[tuple[Path, str, str, str, str]]:
    for key, (title, description, _) in GUIDES.items():
        source = ROOT / f"docs/wiki/{key}.md"
        yield source, title, description, mappings[source.resolve()], "guides"
    for key, (_, title, description) in REFERENCES.items():
        source = ROOT / f"docs/{key}"
        yield source, title, description, mappings[source.resolve()], "guides"
    for key, (slug, title, description) in PROJECT_PAGES.items():
        yield ROOT / key, title, description, f"/{slug}/", "project"


def build_site(output: Path) -> dict[str, object]:
    """Build an allowlisted, self-contained static website; never traverse private history."""
    output = _safe_output(output)
    output.mkdir(parents=True, exist_ok=True)
    _check_existing_output(output)
    match = re.search(r'__version__ = "([^"]+)"', _read(ROOT / "civiscribe/version.py"))
    if match is None:
        raise ValueError("Missing project version.")
    version = match.group(1)
    layout = _read(SOURCE / "layout.html")
    mappings = _mapping()
    search: list[dict[str, str]] = []
    routes: list[str] = []

    def page(route: str, title: str, description: str, content: str, category: str = "") -> None:
        values = {
            "TITLE": html.escape(title),
            "DESCRIPTION": html.escape(description, quote=True),
            "CANONICAL": ORIGIN + BASE + route,
            "ORIGIN": ORIGIN,
            "BASE": BASE,
            "VERSION": version,
            "PAGE": html.escape(category),
            "CONTENT": content,
            "GUIDES_CURRENT": 'aria-current="page"' if category == "guides" else "",
            "PLAY_CURRENT": 'aria-current="page"' if category == "playground" else "",
            "CHANGELOG_CURRENT": 'aria-current="page"' if category == "changelog" else "",
        }
        rendered = layout
        for key, value in values.items():
            rendered = rendered.replace("{{" + key + "}}", value)
        rendered = rendered.replace("{{BASE}}", BASE).replace("{{VERSION}}", version)
        if re.search(r"\{\{[A-Z_]+\}\}", rendered):
            raise ValueError("Unresolved website template value.")
        name = route.strip("/") + "/index.html" if route != "/" else "index.html"
        if route == "/404.html":
            name = "404.html"
        _write(output, name, rendered)
        routes.append(route)
        if route != "/404.html":
            index_content = content.replace("{{BASE}}", BASE).replace("{{VERSION}}", version)
            text = html.unescape(re.sub(r"<[^>]+>", " ", index_content))
            search.append(
                {
                    "title": html.unescape(title).removesuffix(" · CiviScribe"),
                    "description": description,
                    "url": BASE + route,
                    "text": re.sub(r"\s+", " ", text).strip()[:24000],
                }
            )

    page(
        "/",
        "CiviScribe — Your image has a story. Let it travel.",
        "Save ComfyUI images with prompts, settings, and honest metadata. Explore the guides.",
        _read(SOURCE / "home.html"),
        "home",
    )
    page(
        "/guides/",
        "The field guide · CiviScribe",
        "Installation, settings, filenames, workflows, models, privacy, fixes, and automation.",
        _library(),
        "guides",
    )
    page(
        "/playground/",
        "The playground · CiviScribe",
        "Try naming recipes, workflow branches, formats, and synthetic metadata in your browser.",
        _read(SOURCE / "playground.html"),
        "playground",
    )
    for source, title, description, route, category in _document_pages(mappings):
        page(
            route,
            f"{title} · CiviScribe",
            description,
            _guide(source, title, description, route, mappings),
            category,
        )
        search[-1]["text"] = re.sub(r"\s+", " ", _read(source)).strip()[:24000]
    changelog, _ = _render_markdown(ROOT / "CHANGELOG.md", mappings)
    page(
        "/changelog/",
        "What's new · CiviScribe",
        "Release history: naming, active branches, API integration, and security maintenance.",
        _template("changelog.html", {"CHANGELOG": changelog}),
        "changelog",
    )
    page(
        "/404.html",
        "A page wandered off · CiviScribe",
        "Find your way back to the CiviScribe guides and playground.",
        _read(SOURCE / "not-found.html"),
    )
    _copy_assets(output, version)
    _write(
        output,
        "search-index.json",
        json.dumps(search, ensure_ascii=False, separators=(",", ":")) + "\n",
    )
    entries = "".join(
        f"<url><loc>{ORIGIN}{BASE}{route}</loc></url>" for route in routes if route != "/404.html"
    )
    _write(
        output,
        "sitemap.xml",
        f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{entries}</urlset>\n',
    )
    _write(output, "robots.txt", f"User-agent: *\nAllow: /\nSitemap: {ORIGIN}{BASE}/sitemap.xml\n")
    _write(output, ".nojekyll", "")
    facts = {
        "version": version,
        "pages": len(routes),
        "searchablePages": len(search),
        "guideSources": len(GUIDES),
        "technicalReferences": len(REFERENCES),
        "projectPages": len(PROJECT_PAGES),
        "files": {
            path.relative_to(output).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(output.rglob("*"))
            if path.is_file() and path.name != "site-manifest.json"
        },
    }
    _write(output, "site-manifest.json", json.dumps(facts, indent=2) + "\n")
    return facts


def main() -> None:
    """Build the website into an explicitly bounded, ignored output directory."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, default=ROOT / ".tmp/site-preview/ccollins-civiscribe"
    )
    arguments = parser.parse_args()
    facts = build_site(arguments.output)
    print(json.dumps({key: value for key, value in facts.items() if key != "files"}))


if __name__ == "__main__":
    main()
