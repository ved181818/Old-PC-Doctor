# Old PC Doctor v2
# Lightweight, read-only Windows diagnostics. Standard library only.
# Designed for Windows 7+ and Python 3.8+.

import os
import sys
import csv
import time
import shutil
import ctypes
import platform
import subprocess
import tempfile
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from datetime import datetime
try:
    import winreg
except ImportError:
    winreg = None


APP_TITLE = "Old PC Doctor v2.1"
REFRESH_MS = 2500


def format_bytes(value):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return "Unknown"
    units = ("B", "KB", "MB", "GB", "TB")
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return "{:.1f} {}".format(value, unit)
        value /= 1024.0


def run_command(args, timeout=8):
    """Run a read-only Windows diagnostic command and return its output."""
    try:
        startupinfo = None
        creationflags = 0
        if os.name == "nt":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        result = subprocess.run(
            args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            universal_newlines=True, timeout=timeout,
            startupinfo=startupinfo, creationflags=creationflags,
            shell=False
        )
        return result.returncode, (result.stdout or "").strip(), (result.stderr or "").strip()
    except Exception as exc:
        return 1, "", str(exc)


def get_memory():
    if os.name != "nt":
        return None
    class MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [
            ("dwLength", ctypes.c_ulong),
            ("dwMemoryLoad", ctypes.c_ulong),
            ("ullTotalPhys", ctypes.c_ulonglong),
            ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong),
            ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong),
            ("ullAvailVirtual", ctypes.c_ulonglong),
            ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]
    status = MEMORYSTATUSEX()
    status.dwLength = ctypes.sizeof(status)
    try:
        ok = ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
        if not ok:
            return None
        return {
            "total": status.ullTotalPhys,
            "available": status.ullAvailPhys,
            "used": status.ullTotalPhys - status.ullAvailPhys,
            "percent": status.dwMemoryLoad,
        }
    except Exception:
        return None


class CpuSampler:
    """Measures CPU load using Windows GetSystemTimes."""
    def __init__(self):
        self.previous = None
        self.available = os.name == "nt"

    def sample(self):
        if not self.available:
            return None
        idle = ctypes.c_ulonglong()
        kernel = ctypes.c_ulonglong()
        user = ctypes.c_ulonglong()
        try:
            ok = ctypes.windll.kernel32.GetSystemTimes(
                ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)
            )
            if not ok:
                return None
            current = (idle.value, kernel.value, user.value)
            old = self.previous
            self.previous = current
            if old is None:
                return None
            idle_delta = current[0] - old[0]
            total_delta = (current[1] - old[1]) + (current[2] - old[2])
            if total_delta <= 0:
                return 0.0
            return max(0.0, min(100.0, (1.0 - idle_delta / float(total_delta)) * 100.0))
        except Exception:
            self.available = False
            return None


def get_uptime():
    if os.name == "nt":
        try:
            seconds = ctypes.windll.kernel32.GetTickCount64() / 1000.0
            days = int(seconds // 86400)
            hours = int((seconds % 86400) // 3600)
            minutes = int((seconds % 3600) // 60)
            return "{} days, {} hours, {} minutes".format(days, hours, minutes)
        except Exception:
            pass
    return "Unavailable"


def get_startup_items():
    items = []
    if winreg is None:
        return items
    locations = [
        (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", "Current user"),
        (winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\Run", "All users"),
    ]
    for hive, path, scope in locations:
        try:
            key = winreg.OpenKey(hive, path)
            index = 0
            while True:
                try:
                    name, value, _ = winreg.EnumValue(key, index)
                    items.append((scope, name, str(value)))
                    index += 1
                except OSError:
                    break
            winreg.CloseKey(key)
        except OSError:
            continue
    return items


def get_disk_rows():
    rows = []
    if os.name == "nt":
        drives = []
        try:
            mask = ctypes.windll.kernel32.GetLogicalDrives()
            for i in range(26):
                if mask & (1 << i):
                    drives.append(chr(65 + i) + ":\\")
        except Exception:
            drives = ["C:\\"]
    else:
        drives = [os.path.abspath(os.sep)]
    for drive in drives:
        try:
            usage = shutil.disk_usage(drive)
            rows.append((drive, usage.total, usage.used, usage.free,
                         (usage.used / float(usage.total) * 100.0) if usage.total else 0))
        except Exception:
            rows.append((drive, 0, 0, 0, 0))
    return rows


def get_smart_status():
    if os.name != "nt":
        return "SMART status query is available only on Windows."
    code, output, error = run_command(
        ["wmic", "diskdrive", "get", "model,status"], timeout=10
    )
    if code != 0 or not output:
        return "Could not read SMART status. WMIC may be unavailable or access may be restricted."
    return output


def get_process_rows():
    if os.name != "nt":
        return []
    code, output, error = run_command(["tasklist", "/FO", "CSV", "/NH"], timeout=10)
    if code != 0 or not output:
        return []
    rows = []
    try:
        for row in csv.reader(output.splitlines()):
            if len(row) >= 5:
                rows.append((row[0], row[1], row[4]))
    except Exception:
        return []
    return rows


def scan_temp_folders():
    """Bounded, read-only preview: never deletes or changes files."""
    folders = []
    for path in (tempfile.gettempdir(), os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Temp")):
        if path and path not in folders and os.path.isdir(path):
            folders.append(path)
    results = []
    for folder in folders:
        total = 0
        count = 0
        errors = 0
        start = time.time()
        try:
            for root, dirs, files in os.walk(folder):
                # Keep the preview bounded on old machines.
                dirs[:] = [d for d in dirs if not os.path.islink(os.path.join(root, d))]
                for name in files:
                    if count >= 2500 or time.time() - start > 4:
                        break
                    full = os.path.join(root, name)
                    try:
                        total += os.path.getsize(full)
                        count += 1
                    except OSError:
                        errors += 1
                if count >= 2500 or time.time() - start > 4:
                    break
        except OSError:
            errors += 1
        limited = count >= 2500 or time.time() - start > 4
        results.append((folder, count, total, errors, limited))
    return results


class OldPCDoctor:
    def __init__(self, root):
        self.root = root
        self.root.title(APP_TITLE)
        self.root.geometry("900x650")
        self.root.minsize(760, 540)
        self.root.configure(bg="#101820")
        self.cpu = CpuSampler()
        self.last_report = ""
        self.scan_busy = False

        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure("TNotebook", background="#101820", borderwidth=0)
        style.configure("TNotebook.Tab", padding=(12, 7))
        style.configure("Treeview", rowheight=25)
        style.configure("Treeview.Heading", font=("Segoe UI", 9, "bold"))

        header = tk.Frame(root, bg="#172b3a", padx=18, pady=13)
        header.pack(fill="x")
        tk.Label(header, text="OLD PC DOCTOR", bg="#172b3a", fg="#ffffff",
                 font=("Segoe UI", 17, "bold")).pack(side="left")
        tk.Label(header, text="v2.1  |  Lightweight diagnostics", bg="#172b3a",
                 fg="#a9c5d8", font=("Segoe UI", 9)).pack(side="left", padx=12, pady=6)
        self.status = tk.StringVar(value="Ready")
        tk.Label(header, textvariable=self.status, bg="#172b3a", fg="#a9c5d8",
                 font=("Segoe UI", 9)).pack(side="right")

        self.notebook = ttk.Notebook(root)
        self.notebook.pack(fill="both", expand=True, padx=12, pady=12)

        self.overview_tab = tk.Frame(self.notebook, bg="#101820")
        self.performance_tab = tk.Frame(self.notebook, bg="#101820")
        self.storage_tab = tk.Frame(self.notebook, bg="#101820")
        self.startup_tab = tk.Frame(self.notebook, bg="#101820")
        self.cleanup_tab = tk.Frame(self.notebook, bg="#101820")
        self.report_tab = tk.Frame(self.notebook, bg="#101820")
        for tab, title in [
            (self.overview_tab, "Overview"),
            (self.performance_tab, "Performance"),
            (self.storage_tab, "Storage"),
            (self.startup_tab, "Startup"),
            (self.cleanup_tab, "Temp Preview"),
            (self.report_tab, "Report"),
        ]:
            self.notebook.add(tab, text=title)

        self.build_overview()
        self.build_performance()
        self.build_storage()
        self.build_startup()
        self.build_cleanup()
        self.build_report()

        footer = tk.Frame(root, bg="#101820")
        footer.pack(fill="x", padx=12, pady=(0, 10))
        tk.Button(footer, text="Refresh", command=self.refresh_all,
                  bg="#236b8e", fg="white", relief="flat", padx=16, pady=7).pack(side="left")
        tk.Button(footer, text="Export Report", command=self.export_report,
                  bg="#287a58", fg="white", relief="flat", padx=16, pady=7).pack(side="left", padx=8)
        tk.Label(footer, text="Read-only: no files, registry entries or settings are changed.",
                 bg="#101820", fg="#9eb0bc", font=("Segoe UI", 8)).pack(side="right")

        self.refresh_all()
        self.root.after(REFRESH_MS, self.update_live_stats)

    def make_text(self, parent, height=12):
        widget = tk.Text(parent, bg="#172430", fg="#e7edf2", insertbackground="white",
                         relief="flat", wrap="word", font=("Consolas", 9), height=height,
                         padx=10, pady=9)
        return widget

    def build_overview(self):
        tk.Label(self.overview_tab, text="System overview", bg="#101820", fg="white",
                 font=("Segoe UI", 15, "bold")).pack(anchor="w", padx=16, pady=(15, 8))
        self.overview_text = self.make_text(self.overview_tab, 18)
        self.overview_text.pack(fill="both", expand=True, padx=16, pady=8)
        self.overview_text.configure(state="disabled")

    def build_performance(self):
        tk.Label(self.performance_tab, text="Live performance snapshot", bg="#101820",
                 fg="white", font=("Segoe UI", 15, "bold")).pack(anchor="w", padx=16, pady=(15, 8))
        self.cpu_label = tk.StringVar(value="CPU usage: measuring...")
        self.ram_label = tk.StringVar(value="RAM: measuring...")
        for var in (self.cpu_label, self.ram_label):
            tk.Label(self.performance_tab, textvariable=var, bg="#172b3a", fg="#e7edf2",
                     font=("Segoe UI", 12), padx=12, pady=12, anchor="w").pack(fill="x", padx=16, pady=5)
        tk.Label(self.performance_tab, text="Top running processes (tasklist snapshot)",
                 bg="#101820", fg="#c4d4df", font=("Segoe UI", 10, "bold")).pack(anchor="w", padx=16, pady=(14, 5))
        self.process_tree = ttk.Treeview(self.performance_tab,
                                         columns=("name", "pid", "memory"), show="headings", height=11)
        self.process_tree.heading("name", text="Process")
        self.process_tree.heading("pid", text="PID")
        self.process_tree.heading("memory", text="Memory")
        self.process_tree.column("name", width=300)
        self.process_tree.column("pid", width=90)
        self.process_tree.column("memory", width=150)
        self.process_tree.pack(fill="both", expand=True, padx=16, pady=(0, 12))
        tk.Label(self.performance_tab, text="Process list is a Windows snapshot; it is not a benchmark.",
                 bg="#101820", fg="#91a5b3", font=("Segoe UI", 8)).pack(anchor="w", padx=16, pady=(0, 8))

    def build_storage(self):
        tk.Label(self.storage_tab, text="Drive space", bg="#101820", fg="white",
                 font=("Segoe UI", 15, "bold")).pack(anchor="w", padx=16, pady=(15, 8))
        self.disk_tree = ttk.Treeview(self.storage_tab,
            columns=("total", "used", "free", "percent"), show="headings", height=7)
        for col, heading, width in [
            ("total", "Total", 130), ("used", "Used", 130),
            ("free", "Free", 130), ("percent", "Used %", 100)
        ]:
            self.disk_tree.heading(col, text=heading)
            self.disk_tree.column(col, width=width, anchor="center")
        self.disk_tree.pack(fill="x", padx=16, pady=8)
        tk.Label(self.storage_tab, text="Drive health (WMIC / SMART status, if supported)",
                 bg="#101820", fg="#c4d4df", font=("Segoe UI", 10, "bold")).pack(anchor="w", padx=16, pady=(12, 5))
        self.smart_text = self.make_text(self.storage_tab, 9)
        self.smart_text.pack(fill="both", expand=True, padx=16, pady=(0, 12))
        self.smart_text.configure(state="disabled")
        tk.Label(self.storage_tab, text="SMART status is only a basic indicator. 'OK' does not guarantee a healthy disk.",
                 bg="#101820", fg="#91a5b3", font=("Segoe UI", 8)).pack(anchor="w", padx=16, pady=(0, 8))

    def build_startup(self):
        tk.Label(self.startup_tab, text="Startup applications (read-only)", bg="#101820",
                 fg="white", font=("Segoe UI", 15, "bold")).pack(anchor="w", padx=16, pady=(15, 8))
        self.startup_tree = ttk.Treeview(self.startup_tab,
            columns=("scope", "name", "command"), show="headings")
        for col, heading, width in [
            ("scope", "Scope", 110), ("name", "Name", 150), ("command", "Command", 500)
        ]:
            self.startup_tree.heading(col, text=heading)
            self.startup_tree.column(col, width=width, anchor="w")
        self.startup_tree.pack(fill="both", expand=True, padx=16, pady=8)
        tk.Label(self.startup_tab, text="This lists common Run registry entries only. It does not show every startup mechanism.",
                 bg="#101820", fg="#91a5b3", font=("Segoe UI", 8)).pack(anchor="w", padx=16, pady=(0, 8))

    def build_cleanup(self):
        tk.Label(self.cleanup_tab, text="Temporary-file preview", bg="#101820", fg="white",
                 font=("Segoe UI", 15, "bold")).pack(anchor="w", padx=16, pady=(15, 8))
        tk.Label(self.cleanup_tab,
                 text="This feature estimates temporary-folder contents. It does NOT delete anything.",
                 bg="#101820", fg="#c4d4df", font=("Segoe UI", 9)).pack(anchor="w", padx=16, pady=(0, 8))
        self.temp_text = self.make_text(self.cleanup_tab, 16)
        self.temp_text.pack(fill="both", expand=True, padx=16, pady=8)
        self.temp_text.configure(state="disabled")
        tk.Button(self.cleanup_tab, text="Scan temporary folders",
                  command=self.scan_temp_async, bg="#236b8e", fg="white",
                  relief="flat", padx=14, pady=8).pack(anchor="w", padx=16, pady=8)

    def build_report(self):
        tk.Label(self.report_tab, text="Diagnostic report", bg="#101820", fg="white",
                 font=("Segoe UI", 15, "bold")).pack(anchor="w", padx=16, pady=(15, 8))
        self.report_text = self.make_text(self.report_tab, 18)
        self.report_text.pack(fill="both", expand=True, padx=16, pady=8)
        self.report_text.configure(state="disabled")

    def set_text(self, widget, value):
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", value)
        widget.configure(state="disabled")

    def build_report_text(self):
        memory = get_memory()
        disks = get_disk_rows()
        lines = [
            "OLD PC DOCTOR v2.1 - DIAGNOSTIC REPORT",
            "Generated: " + datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "",
            "SYSTEM",
            "Operating system: {} {}".format(platform.system(), platform.release()),
            "Windows details: {}".format(platform.platform()),
            "Computer name: {}".format(platform.node()),
            "Processor: {}".format(platform.processor() or "Not reported"),
            "Logical CPU count: {}".format(os.cpu_count() or "Unknown"),
            "Python: {}".format(sys.version.split()[0]),
            "Uptime: {}".format(get_uptime()),
            "",
            "MEMORY",
        ]
        if memory:
            lines += [
                "Installed/visible RAM: {}".format(format_bytes(memory["total"])),
                "Available RAM: {}".format(format_bytes(memory["available"])),
                "Used RAM: {} ({}%)".format(format_bytes(memory["used"]), memory["percent"]),
            ]
        else:
            lines.append("RAM details unavailable.")
        lines += ["", "DRIVES"]
        for drive, total, used, free, percent in disks:
            if total:
                lines.append("{} Total: {} | Used: {} | Free: {} | Used: {:.1f}%".format(
                    drive, format_bytes(total), format_bytes(used), format_bytes(free), percent))
            else:
                lines.append("{} Unable to read drive information".format(drive))
        lines += [
            "", "LIMITATIONS",
            "- This is a basic diagnostic helper, not a certified hardware test or malware scanner.",
            "- SMART status is a limited disk indicator and may be unavailable or incomplete.",
            "- Startup list covers common Run registry keys only.",
            "- No files are deleted and no system settings or registry values are changed.",
        ]
        return "\n".join(lines)

    def refresh_all(self):
        self.status.set("Refreshing...")
        try:
            memory = get_memory()
            lines = [
                "Operating system : {} {}".format(platform.system(), platform.release()),
                "Windows details  : {}".format(platform.platform()),
                "Computer name    : {}".format(platform.node()),
                "Processor        : {}".format(platform.processor() or "Not reported"),
                "Logical CPUs     : {}".format(os.cpu_count() or "Unknown"),
                "Uptime           : {}".format(get_uptime()),
                "Python           : {}".format(sys.version.split()[0]),
            ]
            if memory:
                lines += [
                    "",
                    "RAM total        : {}".format(format_bytes(memory["total"])),
                    "RAM available    : {}".format(format_bytes(memory["available"])),
                    "RAM used         : {} ({}%)".format(format_bytes(memory["used"]), memory["percent"]),
                ]
            else:
                lines += ["", "RAM information  : Unavailable"]
            self.set_text(self.overview_text, "\n".join(lines))

            for item in self.disk_tree.get_children():
                self.disk_tree.delete(item)
            for drive, total, used, free, percent in get_disk_rows():
                self.disk_tree.insert("", "end", text=drive, values=(
                    format_bytes(total), format_bytes(used), format_bytes(free),
                    "{:.1f}%".format(percent) if total else "Unavailable"
                ))

            for item in self.startup_tree.get_children():
                self.startup_tree.delete(item)
            startup = get_startup_items()
            for row in startup:
                self.startup_tree.insert("", "end", values=row)
            if not startup:
                self.startup_tree.insert("", "end", values=("Info", "No entries found", "Or registry access is unavailable"))

            self.set_text(self.smart_text, get_smart_status())
            self.refresh_processes()
            self.last_report = self.build_report_text()
            self.set_text(self.report_text, self.last_report)
            self.status.set("Updated " + datetime.now().strftime("%H:%M:%S"))
        except Exception as exc:
            self.status.set("Refresh error")
            messagebox.showerror(APP_TITLE, "A diagnostic step failed:\n{}".format(exc))

    def refresh_processes(self):
        rows = get_process_rows()
        for item in self.process_tree.get_children():
            self.process_tree.delete(item)
        # tasklist returns memory as e.g. "12,345 K"; sort by parsed KB.
        def memory_kb(value):
            digits = "".join(ch for ch in value if ch.isdigit())
            return int(digits) if digits else 0
        rows.sort(key=lambda row: memory_kb(row[2]), reverse=True)
        for name, pid, mem in rows[:15]:
            self.process_tree.insert("", "end", values=(name, pid, mem))

    def update_live_stats(self):
        usage = self.cpu.sample()
        if usage is None:
            self.cpu_label.set("CPU usage: measuring / unavailable")
        else:
            self.cpu_label.set("CPU usage: {:.1f}%".format(usage))
        memory = get_memory()
        if memory:
            self.ram_label.set("RAM usage: {} / {} ({}%)".format(
                format_bytes(memory["used"]), format_bytes(memory["total"]), memory["percent"]))
        else:
            self.ram_label.set("RAM usage: unavailable")
        self.root.after(REFRESH_MS, self.update_live_stats)

    def scan_temp_async(self):
        if self.scan_busy:
            return
        self.scan_busy = True
        self.status.set("Scanning temp folders...")
        self.set_text(self.temp_text, "Scanning a limited number of entries. Please wait...")
        def worker():
            results = scan_temp_folders()
            def finish():
                lines = []
                if not results:
                    lines.append("No temporary folders could be inspected.")
                for folder, count, total, errors, limited in results:
                    lines += [
                        "Folder: " + folder,
                        "Files inspected: {}".format(count),
                        "Estimated size: {}".format(format_bytes(total)),
                        "Skipped/unreadable entries: {}".format(errors),
                        "Scan limit reached: {}".format("Yes (estimate may be incomplete)" if limited else "No"),
                        "",
                    ]
                lines += [
                    "IMPORTANT: This is only a preview. No files were removed.",
                    "Some files may be in use. Do not delete temporary files blindly.",
                ]
                self.set_text(self.temp_text, "\n".join(lines))
                self.scan_busy = False
                self.status.set("Temp preview complete")
            self.root.after(0, finish)
        threading.Thread(target=worker, daemon=True).start()

    def export_report(self):
        report = self.build_report_text()
        path = filedialog.asksaveasfilename(
            title="Save diagnostic report",
            defaultextension=".txt",
            filetypes=[("Text report", "*.txt")],
            initialfile="Old_PC_Doctor_Report.txt"
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(report)
            messagebox.showinfo(APP_TITLE, "Report saved successfully:\n" + path)
            self.status.set("Report exported")
        except Exception as exc:
            messagebox.showerror(APP_TITLE, "Could not save report:\n{}".format(exc))


def main():
    root = tk.Tk()
    app = OldPCDoctor(root)
    root.mainloop()


if __name__ == "__main__":
    main()
