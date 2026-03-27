from __future__ import annotations

from lit_gui.contracts import NavigationTarget, SessionSnapshot, VIEW_ORDER
from lit_gui.views._placeholders import PlaceholderView, build_placeholder_views
from lit_gui.views.files import FilesView
from lit_gui.views.home import HomeView


def build_shell_views(
    snapshot: SessionSnapshot,
    *,
    on_open_requested,
    on_initialize_requested,
    on_recent_requested,
    on_select_file,
    on_refresh_requested,
) -> dict[NavigationTarget, object]:
    views = build_placeholder_views(snapshot)
    views[NavigationTarget.HOME] = HomeView(
        snapshot.home,
        on_open_requested=on_open_requested,
        on_initialize_requested=on_initialize_requested,
        on_recent_requested=on_recent_requested,
    )
    views[NavigationTarget.FILES] = FilesView(
        snapshot.files,
        on_select_file=on_select_file,
        on_refresh_requested=on_refresh_requested,
    )
    return {target: views[target] for target in VIEW_ORDER}


__all__ = [
    "FilesView",
    "HomeView",
    "PlaceholderView",
    "build_placeholder_views",
    "build_shell_views",
]
