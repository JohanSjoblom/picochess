# Move Engines to Backup

This script helps you safely back up your existing chess engine installations before updating to the latest versions.

---

## 📘 Purpose

When you want to refresh your installed engines, you should first move your current engine folders to the backup area.  
This ensures that the old versions are preserved, and that `install-picochess.sh` will automatically download and install fresh engine packages.

---

## ⚙️ Usage

Run the script as the **`pi` user**, not as `root`.

```bash
# Step 1 — Move existing engines to backup
./move-engines-to-backup.sh

# Step 2 — Reinstall latest engines
./install-picochess.sh
```

---

## 📂 What It Does

- Moves the following folders from `/opt/picochess/engines/` to the backup area:
  - `engines/<architecture>` (for example `aarch64` or `x86_64`)
  - `engines/lc0_weights`
- Places the backups inside:
  ```
  /home/pi/pico_backups/current/engines_backup/
  ```
- Overwrites any previous backup of these folders.

---

## 🧩 Notes

- You can run this manually or trigger it from your Python code before setting the usual `install-picochess` update flag.
- The next run of `install-picochess.sh` will detect that the engine folder is missing and reinstall the newest engine package automatically.

---

*Author: Johan Sjöblom*  
*Project: Picochess Engine Management Tools*
