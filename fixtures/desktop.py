import os
import tkinter as tk
from pathlib import Path
import sys

root = tk.Tk()
root.title("Live UI test fixture")
root.geometry("560x350+60+60")
root.configure(bg="#192b42")
state = tk.StringVar(value="BEFORE · Ready for input")
status = tk.Label(root, textvariable=state, fg="white", bg="#192b42", font=("Arial", 23))
status.pack(pady=(35, 20))
entry = tk.Entry(root, width=30, font=("Arial", 18))
entry.pack(pady=8)

def apply():
    state.set("AFTER · " + (entry.get() or "Button clicked"))
    root.configure(bg="#17633b")
    status.configure(bg="#17633b")

tk.Button(root, text="Apply change", command=apply, font=("Arial", 16)).pack(pady=22)
root.lift()
root.attributes("-topmost", True)
root.update()
entry.focus_force()
Path(sys.argv[1]).touch()
if len(sys.argv) == 3:
    root.after(int(sys.argv[2]) * 1000, lambda: os._exit(17))
root.mainloop()
