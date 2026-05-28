import os
import shutil

# Folder to back up
SOURCE_DIR = "/home/pi/Test3"

def backup_all_files(folder_path):
    for filename in os.listdir(folder_path):
        src_path = os.path.join(folder_path, filename)
        # Only back up .py files (not directories or .bak files)
        if os.path.isfile(src_path) and filename.endswith(".py"):
            backup_path = src_path + ".bak"
            try:
                shutil.copy2(src_path, backup_path)
                print(f"Backed up: {filename} → {os.path.basename(backup_path)}")
            except Exception as e:
                print(f"Failed to back up: {filename} - {str(e)}")

if __name__ == "__main__":
    backup_all_files(SOURCE_DIR)
