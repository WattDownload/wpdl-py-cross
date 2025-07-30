import flet as ft
import asyncio
from pathlib import Path
from zipfile import ZipFile
from re import sub, match

# --- Library Imports (No changes here) ---
try:
    from endpoints import (
        fetch_cookies,
        fetch_story_content_zip,
        fetch_story_from_partId,
        fetch_story,
    )
    from epub_generator import EPUBGenerator
    from parser import fetch_image, fetch_tree_images, clean_tree
    LIBRARY_MISSING = False
except ImportError:
    LIBRARY_MISSING = True


# --- Helper Function & Backend Logic (No changes here) ---
def ascii_only(string: str):
    string = string.replace(" ", "_")
    return sub(r"[^qwertyuiopasdfghjklzxcvbnmQWERTYUIOPASDFGHJKLZXCVBNM1234567890\-\_)(`~.><\[\]{}]", "", string)

# --- Updated Backend Logic ---
async def download_wattpad_story(
    url: str,
    username: str,
    password: str,
    download_images: bool,
    status_control: ft.Text,
    page: ft.Page
):
    """
    This is your backend logic. It now saves the file to a temporary location
    in the app's private storage and returns the path to that file.
    """
    # (The initial part of the function for fetching metadata remains the same)
    if LIBRARY_MISSING:
        raise RuntimeError("Could not find library files (endpoints.py, etc.).")

    try:
        id_part = url.split("wattpad.com/")[1]
        if "story/" in id_part:
            id_part = id_part.split("story/")[1]
        ID = id_part.split('-')[0].split('?')[0]
        mode = "story" if "/story/" in url else "part"
    except (IndexError, ValueError):
        raise ValueError("Could not parse the Story ID from the URL.")

    cookies = None
    if username and password:
        status_control.value = "Logging in..."; page.update()
        cookies = await fetch_cookies(username, password)

    status_control.value = "Checking story accessibility..."; page.update()
    try:
        if mode == "story":
            metadata = await fetch_story(ID, cookies)
        else:
            metadata = await fetch_story_from_partId(ID, cookies)
        status_control.value = "✅ Story found! Fetching content..."; page.update()
        await asyncio.sleep(1)
    except Exception as e:
        print(f"Metadata fetch error: {e}")
        raise ConnectionError("Story not found or is inaccessible. It may be deleted, a draft, or require a login.")

    status_control.value = "Fetching cover..."; page.update()
    cover_data = await fetch_image(metadata["cover"].replace("-256-", "-512-"))
    status_control.value = "Fetching story content..."; page.update()
    story_zip_bytes = await fetch_story_content_zip(metadata["id"], cookies)
    archive = ZipFile(story_zip_bytes, "r")
    part_trees = []
    for part in metadata["parts"]:
        if part.get("deleted", False): continue
        part_trees.append(clean_tree(part["title"], part["id"], archive.read(str(part["id"])).decode("utf-8")))
    archive.close()
    images = []
    if download_images:
        status_control.value = "Fetching images..."; page.update()
        images = await asyncio.gather(*[fetch_tree_images(tree) for tree in part_trees])
    
    status_control.value = "Compiling EPUB..."; page.update()
    book = EPUBGenerator(metadata, part_trees, cover_data, images)
    book.compile()
    file_content = book.dump().getvalue()
    
    # --- MODIFICATION START ---
    # Save the generated file to the app's private directory
    suggested_filename = f"{ascii_only(metadata['title'])}.epub"
    temp_dir = Path(page.get_files_dir()) # Get app's private files directory
    temp_dir.mkdir(exist_ok=True)       # Ensure it exists
    temp_file_path = temp_dir / suggested_filename
    
    # Write the EPUB content to the temporary file
    temp_file_path.write_bytes(file_content)

    # Return the path to the temporary file and the suggested name
    return str(temp_file_path), suggested_filename
    # --- MODIFICATION END ---


# --- Flet GUI Application ---
# (Your backend logic like download_wattpad_story, endpoints, etc. remains the same)

def main(page: ft.Page):
    page.title = "Wattpad Downloader"
    page.theme = ft.Theme(color_scheme_seed="orange")
    page.vertical_alignment = ft.MainAxisAlignment.CENTER
    page.horizontal_alignment = ft.CrossAxisAlignment.CENTER
    page.theme_mode = ft.ThemeMode.DARK
    page.window_width = 500
    page.window_height = 650

    # --- UI Reset and Error Handling Logic ---
    def reset_ui():
        """A single function to reset the UI to its initial state."""
        url_input.value = ""
        username_input.value = ""
        password_input.value = ""
        url_input.error_text = None
        download_images_switch.value = True
        advanced_options.controls[0].expanded = False
        switcher.content = input_view
        page.update()

    def close_dialog(e):
        """Close the dialog using page.close and then reset the form fields."""
        page.close(error_dialog)
        reset_ui()

    # --- MODIFIED: Dialog is now opened with page.open() ---
    error_dialog = ft.AlertDialog(
        modal=True,
        title=ft.Text("An Error Occurred"),
        content=ft.Text(""),
        actions=[ft.TextButton("OK", on_click=close_dialog)],
        actions_alignment=ft.MainAxisAlignment.END,
    )
    # The line `page.dialog = error_dialog` is no longer needed.
    
    temp_file_path_to_save = None

    # --- MODIFIED: In your main() function ---

def save_file_result(e: ft.FilePickerResultEvent):
    """
    Callback for when the user has picked a file location.
    This now copies the temp file to the final destination and cleans up.
    """
    nonlocal temp_file_path_to_save
    save_path_str = e.path

    # Case 1: User selected a path to save the file
    if save_path_str and temp_file_path_to_save:
        try:
            temp_path = Path(temp_file_path_to_save)
            dest_path = Path(save_path_str)

            # Copy file from temp location to final destination
            dest_path.write_bytes(temp_path.read_bytes())

            # Show success screen
            switcher.content = success_view
            page.update()

        except Exception as ex:
            error_dialog.content = ft.Text(f"Error saving file: {ex}")
            page.open(error_dialog)
        finally:
            # Clean up the temporary file in all cases
            if temp_path.exists():
                temp_path.unlink()
            temp_file_path_to_save = None
    
    # Case 2: User cancelled the save dialog
    else:
        # If a temp file was created, clean it up
        if temp_file_path_to_save:
            temp_path = Path(temp_file_path_to_save)
            if temp_path.exists():
                temp_path.unlink()
            temp_file_path_to_save = None
        
        # Reset the main UI
        reset_ui()


async def process_url_click(e):
    # This must be declared to modify the variable from the outer scope
    nonlocal temp_file_path_to_save
    
    url_input.error_text = None
    url_pattern = r"(?:https?://)?(www\.)?wattpad\.com/(\d+|story/\d+)(-.*)?"
    if not match(url_pattern, url_input.value.strip()):
        url_input.error_text = "Please enter a valid Wattpad URL."
        page.update()
        return
        
    switcher.content = progress_view
    page.update()
    
    try:
        # --- MODIFIED: Receive temp path and filename ---
        temp_path, filename = await download_wattpad_story(
            url=url_input.value.strip(),
            username=username_input.value.strip(), password=password_input.value,
            download_images=download_images_switch.value,
            status_control=status_text, page=page
        )
        # Store the path for the save_file_result callback
        temp_file_path_to_save = temp_path
        
        status_text.value = "✅ Success! Choose where to save."
        page.update()
        file_picker.save_file(dialog_title="Save Your EPUB", file_name=filename, allowed_extensions=["epub"])

    except Exception as ex:
        # (Error handling logic remains the same)
        print(f"An unexpected error occurred: {ex}")
        switcher.content = input_view
        error_dialog.content = ft.Text(str(ex))
        page.open(error_dialog)

    # (The UI component definitions and layout below are unchanged)
    file_picker = ft.FilePicker(on_result=save_file_result)
    page.overlay.append(file_picker)
    url_input = ft.TextField(label="Wattpad Story URL", hint_text="https://www.wattpad.com/story/123-your-story", width=400, border_radius=ft.border_radius.all(10), on_submit=process_url_click)
    username_input = ft.TextField(label="Username", border_radius=ft.border_radius.all(10))
    password_input = ft.TextField(label="Password", border_radius=ft.border_radius.all(10), password=True, can_reveal_password=True)
    advanced_options = ft.ExpansionPanelList(expand_icon_color=ft.Colors.ORANGE_ACCENT, elevation=2, divider_color=ft.Colors.ORANGE_ACCENT, controls=[ft.ExpansionPanel(header=ft.ListTile(title=ft.Text("Advanced Options (for mature/paid stories)")), content=ft.Column([username_input, password_input, ft.Container(height=10)], spacing=5, horizontal_alignment=ft.CrossAxisAlignment.CENTER))])
    download_images_switch = ft.Switch(label="Download images", value=True)
    download_button = ft.ElevatedButton(text="Process and Download", icon=ft.Icons.DOWNLOAD, on_click=process_url_click, height=50, style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=10)))
    status_text = ft.Text("Enter a link to begin.", text_align=ft.TextAlign.CENTER, size=16)
    input_view = ft.Column([ft.Icon(ft.Icons.CLOUD_DOWNLOAD_ROUNDED, size=40, color="white"), ft.Container(height=10), ft.Text("Wattpad Downloader", size=24, weight=ft.FontWeight.BOLD), ft.Text("Download Wattpad stories as clean EPUB files.", text_align=ft.TextAlign.CENTER), ft.Container(height=20), url_input, advanced_options, ft.Row([download_images_switch], alignment=ft.MainAxisAlignment.CENTER), ft.Container(height=15), download_button], width=400, horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=5)
    progress_view = ft.Column([ft.Container(height=150), ft.ProgressRing(width=48, height=48, stroke_width=5), ft.Container(height=20), status_text, ft.Container(height=250)], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=10)
    switcher = ft.AnimatedSwitcher(content=input_view, transition=ft.AnimatedSwitcherTransition.FADE, duration=300, reverse_duration=300)
    page.add(switcher)

    def restart_app(e):
        """Calls the main UI reset function."""
        reset_ui()

    success_view = ft.Column(
        [
            ft.Container(height=150),
            ft.Icon(ft.Icons.CHECK_CIRCLE_OUTLINE_ROUNDED, color=ft.Colors.GREEN, size=60),
            ft.Container(height=20),
            ft.Text("Download Successful!", size=24, weight=ft.FontWeight.BOLD),
            ft.Text("Your EPUB file has been saved.", text_align=ft.TextAlign.CENTER),
            ft.Container(height=30),
            ft.ElevatedButton(
                "Download Another", 
                icon=ft.Icons.REFRESH_ROUNDED, 
                on_click=restart_app, 
                height=50,
                style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=10))
            )
        ],
        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        spacing=10
    )

if __name__ == "__main__":
    ft.app(target=main)
