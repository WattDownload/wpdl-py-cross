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
    
    # --- FIX 1: Ensure cover image was actually downloaded ---
    if not cover_data:
        raise ConnectionError("Failed to download the story's cover image. The link may be broken.")
    
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
    
    # --- FIX 2: Ensure the generated EPUB file is not empty ---
    # This is the most critical check to prevent the "Document is Empty" error.
    # A valid EPUB, even a basic one, will be larger than a few hundred bytes.
    if not file_content or len(file_content) < 200:
        raise ValueError("Generated EPUB is empty. The story might have no chapters or content could not be parsed.")

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

    # --- UI Reset and Error Handling Logic (Unchanged) ---
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

    error_dialog = ft.AlertDialog(
        modal=True,
        title=ft.Text("An Error Occurred"),
        content=ft.Text(""),
        actions=[ft.TextButton("OK", on_click=close_dialog)],
        actions_alignment=ft.MainAxisAlignment.END,
    )
    
    generated_file_content = None

    def save_file_result(e: ft.FilePickerResultEvent):
        """Callback for when the user has picked a file location (DESKTOP ONLY)."""
        nonlocal generated_file_content
        save_path = e.path
        if save_path and generated_file_content:
            try:
                with open(save_path, "wb") as f:
                    f.write(generated_file_content)
                
                # Switch to the success screen
                switcher.content = success_view
                page.update()

            except Exception as ex:
                error_dialog.content = ft.Text(f"Error saving file: {ex}")
                page.open(error_dialog)
        else:
            # If the user cancelled the save dialog, just reset the UI.
            reset_ui()
    
    # This FilePicker will now only be used for desktop
    file_picker = ft.FilePicker(on_result=save_file_result)
    page.overlay.append(file_picker)

    # --- ⭐️ MODIFIED FUNCTION FOR CROSS-PLATFORM SAVING ⭐️ ---
    # --- The definitive cross-platform function ---
    async def process_url_click(e):
        nonlocal generated_file_content
        
        # (Input validation logic is unchanged...)
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
            
            status_text.value = "✅ Success! Choose where to save."
            page.update()

            # --- Platform-specific saving logic ---
            if page.platform in [ft.PagePlatform.ANDROID, ft.PagePlatform.IOS]:
                # On Mobile, use page.save_file() which opens the native save UI
                # NOTE: The method is awaitable and the content parameter is 'data'
                result_path = await page.save_file(
                    dialog_title="Save Your EPUB",
                    file_name=filename,
                    data=file_bytes
                )
                if result_path:
                    switcher.content = success_view
                    page.update()
                else: 
                    reset_ui()
            else:
                # On Desktop, use the FilePicker as before
                generated_file_content = file_bytes
                file_picker.save_file(
                    dialog_title="Save Your EPUB", 
                    file_name=filename, 
                    allowed_extensions=["epub"]
                )

        except Exception as ex:
            # (Error handling is unchanged...)
            print(f"An unexpected error occurred: {ex}")
            switcher.content = input_view
            error_dialog.content = ft.Text(str(ex))
            page.open(error_dialog)

    # --- UI Component Definitions and Layout (Unchanged) ---
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
