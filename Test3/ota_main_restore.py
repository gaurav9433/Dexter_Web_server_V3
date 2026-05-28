import os
import shutil
import subprocess

FOLDER_PATH = "/home/pi/Test3"
FLAG_PATH = os.path.join(FOLDER_PATH, "update_failed.flag")
BACKUP_SCRIPT = os.path.join(FOLDER_PATH, "ota_restore_backup.py")

def backup_all_py_files(folder_path):
    """Backup only .py files in the folder, excluding existing .bak files."""
    for filename in os.listdir(folder_path):
        src_path = os.path.join(folder_path, filename)
        if os.path.isfile(src_path) and filename.endswith(".py"):
            backup_path = src_path + ".bak"
            try:
                shutil.copy2(src_path, backup_path)
                print(f"Backed up: {filename} → {os.path.basename(backup_path)}")
            except Exception as e:
                print(f"Failed to back up {filename} - {str(e)}")

def remove_old_backups(folder_path):
    """Remove old .bak files from the folder."""
    for filename in os.listdir(folder_path):
        if filename.endswith(".bak"):
            backup_path = os.path.join(folder_path, filename)
            try:
                os.remove(backup_path)
                print(f"Removed old backup: {filename}")
            except Exception as e:
                print(f"Failed to remove old backup {filename} - {str(e)}")

def restore_backups(folder_path):
    print("Checking for update failure flag...")
    if os.path.exists(FLAG_PATH):
        with open(FLAG_PATH, "r") as f:
            flag = f.read().strip()
            if flag == "1":
                print("Flag indicates update failure. Restoring backup files...")
                for filename in os.listdir(folder_path):
                    if filename.endswith(".bak"):
                        original_file = os.path.join(folder_path, filename[:-4])  # Remove .bak
                        backup_file = os.path.join(folder_path, filename)
                        try:
                            shutil.copy2(backup_file, original_file)
                            print(f"Restored: {filename} → {os.path.basename(original_file)}")
                        except Exception as e:
                            print(f"Failed to restore {filename} - {str(e)}")
                try:
                    os.remove(FLAG_PATH)
                    print("Flag removed after successful restore.")
                except Exception as e:
                    print(f"Failed to remove flag: {str(e)}")

                print("Rebooting system after restore...")
                subprocess.call(["nsenter", "-t", "1", "-m", "-u", "-i", "-n", "-p", "--", "/sbin/reboot"])

            elif flag == "0":
                print("Flag is 0: Last update successful. Removing old backups and creating new backups...")
                remove_old_backups(folder_path)
                backup_all_py_files(folder_path)
                print("New backups created.")
                try:
                    os.remove(FLAG_PATH)
                    print("Flag removed after successful backup.")
                except Exception as e:
                    print(f"Failed to remove flag: {str(e)}")
            else:
                print(f"Unknown flag value: {flag}")
    else:
        print("No update failure flag found")
        
if __name__ == "__main__":
    restore_backups(FOLDER_PATH)
