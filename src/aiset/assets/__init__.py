"""Server-side helpers for the shipped browser assets (SPEC_service.md 17/21)."""

from __future__ import annotations

from pathlib import Path

ASSETS_DIR = Path(__file__).parent
ASSET_NAMES = ("aiset.css", "aiset.js", "aiset-tree.js")
# A reference theme a host may adopt, deliberately NOT part of ASSET_NAMES:
# include_assets() must not load it (proposal_improvement4.md item 6).
THEME_NAME = "aiset-host-theme.css"


def include_assets(*, base: str = "/assets") -> str:
    """HTML that includes every shipped asset in dependency order."""
    parts = [f'<link rel="stylesheet" href="{base}/aiset.css">']
    parts.extend(f'<script src="{base}/{name}"></script>' for name in ASSET_NAMES if name.endswith(".js"))
    return "".join(parts)


def render_tree_editor(document: str, options: dict | None = None) -> str:
    """Host fragment of the generated tree editor."""
    del options  # presentation options belong to the host stylesheet
    return (
        include_assets()
        + f'<div class="aiset-tree-editor" data-aiset-tree="{document}">'
        + '<div class="aiset-tree-toolbar" data-role="toolbar"></div>'
        + '<div class="aiset-tree" data-role="tree"></div>'
        + '<div class="aiset-tree-pending" data-role="pending"></div>'
        + '<div class="aiset-tree-status" data-role="status" role="status" aria-live="polite"></div>'
        + '<ul class="aiset-tree-issues" data-role="issues"></ul>'
        + "</div>"
    )


def render_node_editor(document: str, path: str = "", options: dict | None = None) -> str:
    """Host fragment of the single-node path/value editor."""
    del options
    return (
        include_assets()
        + f'<div class="aiset-node-editor" data-aiset-node="{document}" data-aiset-path="{path}"></div>'
    )


def render_full_editor(document: str, options: dict | None = None) -> str:
    """Host fragment of the whole-document editor (the generated tree editor)."""
    return render_tree_editor(document, options)