import os
# Path to the flag file
FLAG_PATH = "/home/pi/Test3/update_failed.flag"

def update_flag(value):
    try:
        with open(FLAG_PATH, "w") as flag_file:
            flag_file.write(value)
        print(f"Flag updated to: {value}")
    except Exception as e:
        print(f"Error updating the flag: {str(e)}")

# Example usage
#update_flag("1")  # Set flag to 1 (indicating failure)
update_flag("0")  # Uncomment to set flag to 0 (indicating success)
