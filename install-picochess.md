# Picochess Installation Script — Variable Overview

This document explains the main variables used in the Picochess installation and update script.

---

**REPO_DIR** - The full path where the Picochess repository is stored.  
Default: `/opt/picochess`

**BACKUP_DIR** - The directory where backups of the current Picochess installation are stored.  
Example: `/home/pi/pico_backups/current`

**TMPFILE** - Temporary file used during downloads, for example engine packages.  
Example: `/home/pi/pico_backups/current/tmp/engines-aarch64-small.tar.gz`

**ENGINE_URL** - The remote URL to download the default engine package from GitHub.

**ARCH** - The detected system architecture, such as `aarch64` or `x86_64`.  
Used to determine which engine package to install.

**BRANCH** - The current Git branch being tracked by the Picochess repository.  
Used to check if updates are available from GitHub.

**TAG_LIMIT** - The number of most recent tags to show when listing available versions.  
Default: `3`

**REMOTE_REPO** - The remote GitHub repository URL used for cloning or fetching updates.  
Default: `https://github.com/JohanSjoblom/picochess`

**GIT_USER** - The user account that performs git operations.  
Default: `pi`

**SERVICE_DIR** - Path to Picochess service files that integrate with `systemd`.  
Example: `/etc/systemd/system`

**PI_USER** - The primary user account on the Raspberry Pi used to run Picochess.  
Default: `pi`

---
