from __future__ import annotations

from PySide6 import QtWidgets

from lit_gui.contracts import (
    BranchesViewState,
    ChangesViewState,
    FilesViewState,
    HistoryViewState,
    HomeViewState,
    NavigationTarget,
    SessionSnapshot,
    SummaryItem,
    VIEW_ORDER,
)


class PlaceholderView(QtWidgets.QWidget):
    def __init__(
        self,
        state: HomeViewState | ChangesViewState | HistoryViewState | BranchesViewState | FilesViewState,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.route = state.route
        self.state = state
        self.title_label = QtWidgets.QLabel(state.title)
        self.subtitle_label = QtWidgets.QLabel(state.subtitle)
        self.section_titles: tuple[str, ...] = ()

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        self.title_label.setWordWrap(True)
        self.subtitle_label.setWordWrap(True)
        layout.addWidget(self.title_label)
        layout.addWidget(self.subtitle_label)

        sections = tuple(_sections_for_state(state))
        self.section_titles = tuple(title for title, _ in sections)
        for title, lines in sections:
            group = QtWidgets.QGroupBox()
            group.setTitle(title)
            group_layout = QtWidgets.QVBoxLayout(group)
            for line in lines:
                label = QtWidgets.QLabel(line)
                label.setWordWrap(True)
                group_layout.addWidget(label)
            layout.addWidget(group)

        layout.addStretch(1)


def build_placeholder_views(snapshot: SessionSnapshot) -> dict[NavigationTarget, PlaceholderView]:
    return {target: PlaceholderView(snapshot.for_view(target)) for target in VIEW_ORDER}


def _sections_for_state(
    state: HomeViewState | ChangesViewState | HistoryViewState | BranchesViewState | FilesViewState,
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    if isinstance(state, HomeViewState):
        recent = tuple(
            f"{entry.name}: {entry.root}"
            for entry in state.recent_repositories
        ) or ("No recent repositories recorded yet.",)
        return (
            ("Highlights", _summary_lines(state.highlights)),
            ("Recent Repositories", recent),
            ("Next Step", (state.call_to_action,)),
        )
    if isinstance(state, ChangesViewState):
        staged = tuple(
            f"{entry.path} [{entry.change_kind}]"
            for entry in state.staged
        ) or ("No staged paths yet.",)
        unstaged = tuple(
            f"{entry.path} [{entry.change_kind}]"
            for entry in state.unstaged
        ) or ("No unstaged paths yet.",)
        return (
            ("Summary", _summary_lines(state.highlights)),
            ("Staged", staged),
            ("Unstaged", unstaged),
            ("Commit", (state.commit_message_hint,)),
        )
    if isinstance(state, HistoryViewState):
        commits = tuple(
            f"{entry.commit_id}: {entry.message}"
            for entry in state.commits
        ) or ("No commits loaded yet.",)
        return (
            ("Summary", _summary_lines(state.highlights)),
            ("Timeline", commits),
        )
    if isinstance(state, BranchesViewState):
        branches = tuple(
            f"{'* ' if entry.is_current else '  '}{entry.name}"
            for entry in state.branches
        ) or ("No branches loaded yet.",)
        return (
            ("Summary", _summary_lines(state.highlights)),
            ("Branch List", branches),
        )
    tree = tuple(
        f"{'  ' * entry.depth}{entry.display_name}"
        for entry in state.tree
    ) or ("No repository tree loaded yet.",)
    return (
        ("Summary", _summary_lines(state.highlights)),
        ("Repository Tree", tree),
    )


def _summary_lines(items: tuple[SummaryItem, ...]) -> tuple[str, ...]:
    return tuple(f"{item.label}: {item.value}" for item in items) or ("No summary available yet.",)
