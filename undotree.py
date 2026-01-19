import sublime
import sublime_plugin
import difflib
import threading

undo_trees = {}
lock = threading.Lock()
PREVIEW_PANEL_NAME = "undotree_diff_preview"

class UndoNode:
    def __init__(self, text, diff, parent=None):
        self.text = text
        self.diff = diff
        self.parent = parent
        self.children = []

class UndoTree:
    def __init__(self, text):
        self.root = UndoNode(text, "Initial state")
        self.current = self.root

    def add(self, new_text):
        if new_text == self.current.text:
            return

        diff = self.make_diff(self.current.text, new_text)
        if not diff.strip():
            return

        node = UndoNode(new_text, diff, self.current)
        self.current.children.append(node)
        self.current = node

    def make_diff(self, old, new):
        diff = difflib.unified_diff(
            old.splitlines(),
            new.splitlines(),
            lineterm=""
        )
        return "\n".join(diff)

# Event listener (file open + save)
class UndoTreeListener(sublime_plugin.EventListener):
    def on_load_async(self, view):
        """Create initial undo node when file is opened"""
        vid = view.id()
        text = view.substr(sublime.Region(0, view.size()))
        with lock:
            if vid not in undo_trees:
                undo_trees[vid] = UndoTree(text)

    def on_post_save_async(self, view):
        if view.is_loading():
            return

        vid = view.id()
        text = view.substr(sublime.Region(0, view.size()))
        with lock:
            if vid not in undo_trees:
                undo_trees[vid] = UndoTree(text)
            else:
                undo_trees[vid].add(text)

    def on_post_save_as_async(self, view):
        self.on_post_save_async(view)

# UndoTree UI commands
class ShowUndoTreeCommand(sublime_plugin.WindowCommand):
    def run(self):
        self.view = self.window.active_view()
        if not self.view:
            return

        self.tree = undo_trees.get(self.view.id())
        if not self.tree:
            sublime.message_dialog("No undo history yet. Save the file first.")
            return

        self.nodes = []
        self.flatten(self.tree.root)
        items = [self.summarize(n.diff) for n in self.nodes]

        # Show quick panel with live highlight preview
        try:
            # Modern builds supporting on_highlight
            self.window.show_quick_panel(
                items,
                self.on_select,       # called when user presses Enter
                sublime.MONOSPACE_FONT,
                -1,                   # selected_index
                self.on_highlight     # called when item is highlighted
            )
        except TypeError:
            # Fallback for older builds (no live preview)
            self.window.show_quick_panel(
                items,
                self.on_select,
                sublime.MONOSPACE_FONT
            )

    def flatten(self, node):
        self.nodes.append(node)
        for child in node.children:
            self.flatten(child)

    def summarize(self, diff):
        if diff == "Initial state":
            return "Initial state"
        added = 0
        removed = 0
        for line in diff.splitlines():
            if line.startswith("+") and not line.startswith("+++"):
                added += 1
            elif line.startswith("-") and not line.startswith("---"):
                removed += 1
        return "+{:<3}  -{:<3}".format(added, removed)

    # Called when user presses Enter
    def on_select(self, index):
        if index == -1:
            return
        node = self.nodes[index]
        undo_trees[self.view.id()].current = node
        self.show_diff_preview(node.diff)
        self.view.run_command("undo_tree_restore", {"text": node.text})

    # Called when user highlights/moves selection
    def on_highlight(self, index):
        if index == -1:
            return
        node = self.nodes[index]
        self.show_diff_preview(node.diff)

    def show_diff_preview(self, diff_text):
        panel = self.window.create_output_panel(PREVIEW_PANEL_NAME)
        panel.set_read_only(False)
        panel.run_command("undotree_write_preview", {"text": diff_text})
        panel.set_read_only(True)
        panel.assign_syntax("Packages/Diff/Diff.sublime-syntax")
        self.window.run_command("show_panel", {"panel": "output." + PREVIEW_PANEL_NAME})

# Text commands
class UndotreeWritePreviewCommand(sublime_plugin.TextCommand):
    def run(self, edit, text):
        self.view.replace(
            edit,
            sublime.Region(0, self.view.size()),
            text if text != "Initial state" else "Initial state\n"
        )

class UndoTreeRestoreCommand(sublime_plugin.TextCommand):
    def run(self, edit, text):
        self.view.replace(
            edit,
            sublime.Region(0, self.view.size()),
            text
        )
