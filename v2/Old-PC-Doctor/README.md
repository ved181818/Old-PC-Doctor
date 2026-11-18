# Old PC Doctor

**A lightweight, read-only Windows diagnostics app for older computers.**

Old PC Doctor displays useful system information in a simple desktop interface. It is designed to be easy to run on modest Windows PCs and uses Python's standard library.

> **Status:** Early community release (v2.1). Tested for Python syntax; real-world compatibility should be verified on each supported Windows version.

## Features

- System overview: Windows version, processor information, logical CPU count, uptime, and Python version.
- Live CPU and RAM usage snapshots.
- Running-process list, including process name, PID, and memory shown by Windows.
- Drive capacity, used space, and free space.
- Basic disk SMART status through WMIC, when available.
- Read-only inspection of common Windows Run registry startup entries.
- Bounded temporary-folder size preview. It does not delete files.
- Exportable plain-text diagnostic report.

## Safety and limitations

Old PC Doctor is an informational helper, **not** a certified hardware diagnostic suite, antivirus, malware scanner, or data-recovery tool.

- It does not delete files.
- It does not change registry entries or Windows settings.
- It does not disable startup applications.
- SMART output is only a basic indicator. An `OK` status does not guarantee that a drive is healthy.
- Startup inspection covers common Run registry keys only, not every Windows startup mechanism.
- Temporary-folder scanning is deliberately bounded; its size estimate may be incomplete.
- Some information may be unavailable depending on Windows edition, permissions, or system configuration.

Always keep backups of important files. Review diagnostic output before making system changes.

## Requirements

- Windows 7 or newer (Windows-specific features may vary by version).
- Python 3.8 or newer.
- Tkinter, normally included with the standard Windows Python installer.
- No third-party Python packages are required.

## Run from source

1. Install Python 3.8+ and ensure **Tcl/Tk support** is included.
2. Download or clone this repository.
3. Open Command Prompt in the project folder.
4. Run:

```bat
python old_pc_doctor\old_pc_doctor.py
```

If `python` points to an older Python installation, use the full path to your Python 3 executable instead. For example:

```bat
"C:\Path\To\Python38\python.exe" old_pc_doctor\old_pc_doctor.py
```

On Windows, you can also double-click `run_old_pc_doctor.bat` if the `python` command points to Python 3.8 or newer.

## Project structure

```text
Old-PC-Doctor/
├── old_pc_doctor/
│   └── old_pc_doctor.py
├── .gitignore
├── CHANGELOG.md
├── LICENSE
├── README.md
├── requirements.txt
└── run_old_pc_doctor.bat
```

## Contributing

Bug reports, compatibility reports, and improvements are welcome. When reporting a problem, include:

- Windows version and whether it is 32-bit or 64-bit.
- Python version.
- The exact error message or a screenshot.
- Which tab or action caused the issue.

Please do not include passwords, licence keys, personal documents, or private diagnostic details in public issue reports.

## Licence

This project is released under the MIT License. See [LICENSE](LICENSE).

## Disclaimer

Provided "as is", without warranty of any kind. You are responsible for deciding how to use the information it displays.
