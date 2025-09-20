import os
import sys
import dropbox

# --- Get your access token from an environment variable ---
# It's safer than pasting it directly into the script.
ACCESS_TOKEN = os.getenv('DROPBOX_TOKEN')
DROPBOX_HEALTH_METRICS_DIR = os.getenv('DROPBOX_HEALTH_METRICS_DIR')

if not ACCESS_TOKEN:
    print("Error: DROPBOX_TOKEN environment variable not set.")
    print("Please set it before running the script.")
    sys.exit(1)

# --- Main script logic ---
print("Connecting to Dropbox with the provided token...")

try:
    # Create a Dropbox client instance
    dbx = dropbox.Dropbox(ACCESS_TOKEN)

    # Check account info to verify the token is valid
    account = dbx.users_get_current_account()
    print(f"✅ Successfully connected to the account of: {account.name.display_name}")

    # Attempt to list the contents of the root folder
    # The root folder in the Dropbox API is represented by an empty string: ''
    print("\nAttempting to list contents of the root folder ('/')...")
    result = dbx.files_list_folder(path=DROPBOX_HEALTH_METRICS_DIR)

    print("\n--- Root Folder Contents ---")
    if not result.entries:
        print("The root folder is empty or the token can't see any files here.")
    else:
        for entry in result.entries:
            # Check if the entry is a folder or a file
            entry_type = "Folder" if isinstance(entry, dropbox.files.FolderMetadata) else "File"
            print(f"- {entry.name} ({entry_type})")
    print("----------------------------\n")
    print("✅ Script finished successfully.")

except dropbox.exceptions.AuthError:
    print("\n❌ AUTHENTICATION ERROR:")
    print("The access token is invalid, expired, or does not have the required permissions (scopes).")
    print("Please ensure your token is correct and has the 'files.metadata.read' scope enabled.")
    sys.exit(1)

except dropbox.exceptions.ApiError as err:
    print(f"\n❌ API ERROR: {err}")
    print("This can happen if the app does not have permission to access the root folder.")
    sys.exit(1)

except Exception as err:
    print(f"\n❌ An unexpected error occurred: {err}")
    sys.exit(1)