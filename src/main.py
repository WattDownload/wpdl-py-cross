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
    This is your backend logic, with more robust ID parsing.
    """
    if LIBRARY_MISSING:
        raise RuntimeError("Could not find library files (endpoints.py, etc.).")

    # --- FIXED: More robust ID parsing ---
    # It now correctly handles URLs with or without a title slug (e.g., /story/12345)
    try:
        id_part = url.split("wattpad.com/")[1]
        if "story/" in id_part:
            id_part = id_part.split("story/")[1]
        ID = id_part.split('-')[0]
        mode = "story" if "/story/" in url else "part"
    except (IndexError, ValueError):
        raise ValueError("Could not parse the Story ID from the URL.")
    # --- End of fix ---

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

    # (The rest of this function is unchanged)
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
    suggested_filename = f"{ascii_only(metadata['title'])}.epub"
    return file_content, suggested_filename


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
    
    generated_file_content = None

    def save_file_result(e: ft.FilePickerResultEvent):
        """Callback for when the user has picked a file location."""
        nonlocal generated_file_content
        save_path = e.path
        if save_path and generated_file_content:
            try:
                with open(save_path, "wb") as f:
                    f.write(generated_file_content)
                page.snack_bar = ft.SnackBar(content=ft.Text(f"Successfully saved!"), bgcolor=ft.Colors.GREEN_700)
                page.snack_bar.open = True
                page.update()
            except Exception as ex:
                error_dialog.content = ft.Text(f"Error saving file: {ex}")
                page.open(error_dialog) # Use page.open() here as well
        else:
            # If the user cancelled the save dialog, just reset the UI.
            reset_ui()


    async def process_url_click(e):
        nonlocal generated_file_content
        
        url_input.error_text = None
        url_pattern = r"(?:https?://)?(www\.)?wattpad\.com/(\d+|story/\d+)(-.*)?"
        if not match(url_pattern, url_input.value.strip()):
            url_input.error_text = "Please enter a valid Wattpad URL."
            page.update()
            return
            
        switcher.content = progress_view
        page.update()
        
        try:
            file_bytes, filename = await download_wattpad_story(
                url=url_input.value.strip(),
                username=username_input.value.strip(), password=password_input.value,
                download_images=download_images_switch.value,
                status_control=status_text, page=page
            )
            generated_file_content = file_bytes
            status_text.value = "✅ Success! Choose where to save."
            page.update()
            file_picker.save_file(dialog_title="Save Your EPUB", file_name=filename, allowed_extensions=["epub"])

        except Exception as ex:
            # --- FIXED: This block now reliably shows the error dialog ---
            print(f"An unexpected error occurred: {ex}")
            
            # 1. Immediately switch back to the input form so you're not stuck.
            switcher.content = input_view
            
            # 2. Set the dialog's error message.
            error_dialog.content = ft.Text(str(ex))
            
            # 3. Open the dialog using the page.open() method.
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
    switcher = ft.AnimatedSwitcher(content=input_view, transition=ft.AnimatedSwitcherTransition.SCALE, duration=300, reverse_duration=300)
    page.add(switcher)

if __name__ == "__main__":
    ft.app(target=main)