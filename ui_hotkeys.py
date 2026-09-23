"""Layout-independent edit hotkeys for Tk Entry/Text on Windows."""

from __future__ import annotations

import tkinter as tk

# Windows virtual-key codes — physical key, not RU/EN layout.
_VK_BACK = 8
_VK_DELETE = 46
_VK_A, _VK_C, _VK_V, _VK_X, _VK_Y, _VK_Z = 65, 67, 86, 88, 89, 90
_CTRL_BIT = 0x4
_SHIFT_BIT = 0x1
_ALT_BIT = 0x20000  # 0x8 is NumLock on Windows Tk — do not treat it as Alt


def enable_edit_hotkeys(widget: tk.Text | tk.Entry) -> None:
    """Ctrl+A/C/V/X/Z/Y and word delete, independent of keyboard layout."""
    if isinstance(widget, tk.Entry):
        _attach_entry_undo(widget)
    widget.bind("<KeyPress>", lambda e, w=widget: _on_edit_key(e, w))


def _attach_entry_undo(entry: tk.Entry) -> None:
    state = {"stack": [entry.get()], "index": 0, "lock": False}

    def remember(_event=None) -> None:
        if state["lock"]:
            return
        val = entry.get()
        if state["stack"][state["index"]] == val:
            return
        state["stack"] = state["stack"][: state["index"] + 1]
        state["stack"].append(val)
        if len(state["stack"]) > 200:
            state["stack"].pop(0)
        state["index"] = len(state["stack"]) - 1

    def undo() -> None:
        if state["index"] <= 0:
            return
        state["lock"] = True
        state["index"] -= 1
        entry.delete(0, tk.END)
        entry.insert(0, state["stack"][state["index"]])
        entry.icursor(tk.END)
        state["lock"] = False

    def redo() -> None:
        if state["index"] >= len(state["stack"]) - 1:
            return
        state["lock"] = True
        state["index"] += 1
        entry.delete(0, tk.END)
        entry.insert(0, state["stack"][state["index"]])
        entry.icursor(tk.END)
        state["lock"] = False

    entry.bind("<KeyRelease>", remember, add="+")
    entry.bind("<<Paste>>", lambda _e: entry.after_idle(remember), add="+")
    entry.bind("<<Cut>>", lambda _e: entry.after_idle(remember), add="+")
    entry._edit_undo = undo  # type: ignore[attr-defined]
    entry._edit_redo = redo  # type: ignore[attr-defined]
    entry._edit_remember = remember  # type: ignore[attr-defined]


def _on_edit_key(event: tk.Event, widget: tk.Text | tk.Entry) -> str | None:
    if not (event.state & _CTRL_BIT) or (event.state & _ALT_BIT):
        return None
    if str(widget.cget("state")) == "disabled":
        return "break"
    code = int(event.keycode)
    shift = bool(event.state & _SHIFT_BIT)
    try:
        if code == _VK_A and not shift:
            _select_all(widget)
        elif code == _VK_C and not shift:
            widget.event_generate("<<Copy>>")
        elif code == _VK_X and not shift:
            widget.event_generate("<<Cut>>")
        elif code == _VK_V and not shift:
            widget.event_generate("<<Paste>>")
        elif code == _VK_Z:
            _redo(widget) if shift else _undo(widget)
        elif code == _VK_Y and not shift:
            _redo(widget)
        elif code == _VK_BACK and not shift:
            _delete_word(widget, back=True)
        elif code == _VK_DELETE and not shift:
            _delete_word(widget, back=False)
        elif 65 <= code <= 90:
            pass  # Ctrl+letter must not insert a Cyrillic char
        else:
            return None
    except tk.TclError:
        return "break"
    return "break"


def _select_all(widget: tk.Text | tk.Entry) -> None:
    if isinstance(widget, tk.Text):
        widget.tag_remove("sel", "1.0", "end")
        widget.tag_add("sel", "1.0", "end-1c")
        widget.mark_set("insert", "end-1c")
        widget.see("insert")
        return
    widget.selection_range(0, tk.END)
    widget.icursor(tk.END)


def _undo(widget: tk.Text | tk.Entry) -> None:
    if isinstance(widget, tk.Text):
        widget.edit_undo()
        return
    widget._edit_undo()  # type: ignore[attr-defined]


def _redo(widget: tk.Text | tk.Entry) -> None:
    if isinstance(widget, tk.Text):
        widget.edit_redo()
        return
    widget._edit_redo()  # type: ignore[attr-defined]


def _delete_word(widget: tk.Text | tk.Entry, *, back: bool) -> None:
    if isinstance(widget, tk.Text):
        if back:
            if widget.compare("insert", ">", "1.0"):
                widget.delete("insert -1c wordstart", "insert")
        elif widget.compare("insert", "<", "end-1c"):
            widget.delete("insert", "insert wordend")
        return
    pos = int(widget.index(tk.INSERT))
    text = widget.get()
    if back:
        i = pos
        while i > 0 and text[i - 1].isspace():
            i -= 1
        while i > 0 and not text[i - 1].isspace():
            i -= 1
    else:
        i = pos
        n = len(text)
        while i < n and not text[i].isspace():
            i += 1
        while i < n and text[i].isspace():
            i += 1
    if i != pos:
        widget.delete(min(i, pos), max(i, pos))
        remember = getattr(widget, "_edit_remember", None)
        if remember:
            remember()
