"""Desktop widget exercising native pointer, key, focus, and window events."""

import json
from pathlib import Path
import sys
import time
import tkinter as tk


WIDTH, HEIGHT = 620, 420
ANCHOR = "#fa4090"
REQUIRED_EVENTS = {
    "dragged", "hovered", "double_clicked", "opened_context_menu", "held", "scrolled",
    "shortcut", "detail_opened", "detail_focused", "detail_closed", "received_multiline_text",
}
TEXT = "مَرْحَبًا ١٢٣؟\nNotes 👩🏽‍💻 and العربية"


def main(directory):
    root = tk.Tk()
    root.title("Native interaction fixture")
    root.geometry(f"{WIDTH}x{HEIGHT}+48+65")
    root.resizable(False, False)
    root.configure(bg="#253446")
    canvas = tk.Canvas(root, width=WIDTH, height=HEIGHT, bg="#253446", highlightthickness=0)
    canvas.pack()
    canvas.create_rectangle(0, 0, 12, 12, fill=ANCHOR, outline="")
    measured = {}
    zones = {}
    start = {}

    def mark(event, details=True):
        measured[event] = details
        if event in zones:
            canvas.itemconfigure(zones[event], fill="#17633b")
        pending = directory / "events.tmp"
        pending.write_text(json.dumps(measured, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        pending.replace(directory / "events.json")

    def zone(event, label, x, y, width=132):
        tag = f"zone-{event}"
        shape = canvas.create_rectangle(x, y, x + width, y + 55, outline="#ffffff", fill="#3b526b", tags=tag)
        canvas.create_text(x + width // 2, y + 27, text=label, fill="white", font=("Arial", 13), tags=tag)
        zones[event] = shape
        return tag

    source = zone("drag_source", "Drag source", 23, 24)
    hover = zone("hovered", "Hover", 177, 24)
    double = zone("double_clicked", "Double-click", 331, 24)
    context = zone("opened_context_menu", "Right-click", 465, 24, 130)
    held = zone("held", "Hold", 23, 102)
    zone("dragged", "Drop here", 177, 102)
    zone("scrolled", "Scroll", 331, 102, 264)

    canvas.tag_bind(source, "<ButtonPress-1>", lambda _: start.update(drag=True))
    canvas.tag_bind(hover, "<Enter>", lambda _: mark("hovered"))
    canvas.tag_bind(double, "<Double-Button-1>", lambda _: mark("double_clicked"))
    canvas.tag_bind(held, "<ButtonPress-1>", lambda _: start.update(held=time.monotonic()))

    def release(event):
        if start.pop("drag", False) and 177 <= event.x <= 309 and 102 <= event.y <= 157:
            mark("dragged")
        pressed = start.pop("held", None)
        if pressed is not None and time.monotonic() - pressed >= .4:
            mark("held")

    def scroll(event):
        if 331 <= event.x <= 595 and 102 <= event.y <= 157:
            mark("scrolled")

    canvas.bind("<ButtonRelease-1>", release)
    for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
        canvas.bind(sequence, scroll)

    menu = tk.Menu(root, tearoff=False)
    menu.add_command(label="Fixture context item", command=lambda: mark("context_item"))

    def context_menu(event):
        mark("opened_context_menu")
        menu.post(event.x_root, event.y_root)

    for sequence in ("<Button-2>", "<Button-3>", "<Control-Button-1>"):
        canvas.tag_bind(context, sequence, context_menu)

    canvas.create_text(24, 185, anchor="nw", text="Multiline input and F6 shortcut", fill="white", font=("Arial", 14))
    editor = tk.Text(root, height=4, wrap="word", font=("Arial", 15))
    canvas.create_window(24, 210, width=570, height=103, window=editor, anchor="nw")

    def check_text(_event):
        if editor.edit_modified():
            editor.edit_modified(False)
            current = editor.get("1.0", "end-1c")
            if current == TEXT:
                mark("received_multiline_text", current)

    editor.bind("<<Modified>>", check_text)
    root.bind("<F6>", lambda _: mark("shortcut"))

    def detail():
        second = tk.Toplevel(root)
        second.title("Native interaction detail")
        second.geometry("230x150+685+86")
        mark("detail_opened")
        field = tk.Entry(second)
        field.pack(padx=20, pady=20)
        field.insert(0, "Detail window")
        second.bind("<FocusIn>", lambda _: mark("detail_focused"))

        def close():
            mark("detail_closed")
            second.destroy()

        second.protocol("WM_DELETE_WINDOW", close)

    button = tk.Button(root, text="Open detail window", command=detail)
    canvas.create_window(24, 359, window=button, anchor="nw")
    root.lift()
    root.attributes("-topmost", True)
    root.update()
    (directory / "ready").touch()
    root.mainloop()


if __name__ == "__main__":
    directory = Path(sys.argv[1])
    if len(sys.argv) == 3 and sys.argv[2] == "verify":
        events = json.loads((directory / "events.json").read_text(encoding="utf-8"))
        if missing := REQUIRED_EVENTS - events.keys():
            raise SystemExit(f"Native events were missing: {sorted(missing)}")
        if events["received_multiline_text"] != TEXT:
            raise SystemExit("The fixture did not receive the exact multiline Unicode text")
        print(f"Verified {len(REQUIRED_EVENTS)} native events and exact Unicode input")
    else:
        directory.mkdir(parents=True, exist_ok=True)
        main(directory)
