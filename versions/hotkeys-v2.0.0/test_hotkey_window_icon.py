from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
import tkinter as tk

from war3_hotkey_tool import HotkeyToolApp


def configure_icon(png_exists=True, ico_exists=True, photo_error=None):
    root = Mock()
    app = SimpleNamespace(root=root, tr=lambda key: key)
    png = Mock(spec=Path)
    png.exists.return_value = png_exists
    ico = Mock(spec=Path)
    ico.exists.return_value = ico_exists
    image = Mock()
    with patch("war3_hotkey_tool.ICON_PNG_PATH", png), patch(
        "war3_hotkey_tool.ICON_PATH", ico
    ), patch("war3_hotkey_tool.tk.PhotoImage", return_value=image, side_effect=photo_error) as photo:
        HotkeyToolApp._configure_window(app)
    return app, photo, image


def test_high_resolution_png_is_preferred_and_retained():
    app, photo, image = configure_icon()
    assert photo.call_args.kwargs["master"] is app.root
    assert app.app_icon is image
    app.root.iconphoto.assert_called_once_with(True, image)
    app.root.iconbitmap.assert_not_called()


def test_missing_png_falls_back_to_ico():
    app, photo, _ = configure_icon(png_exists=False)
    photo.assert_not_called()
    app.root.iconbitmap.assert_called_once()
    assert app.app_icon is None


def test_unreadable_png_falls_back_to_ico():
    app, _, _ = configure_icon(photo_error=tk.TclError("invalid image"))
    app.root.iconbitmap.assert_called_once()
    assert app.app_icon is None


def test_missing_icons_do_not_prevent_startup():
    app, photo, _ = configure_icon(png_exists=False, ico_exists=False)
    photo.assert_not_called()
    app.root.iconphoto.assert_not_called()
    app.root.iconbitmap.assert_not_called()


def test_high_resolution_png_is_in_release_spec():
    spec = Path(__file__).with_name("War3ReforgedHotkeys.spec").read_text(encoding="utf-8")
    assert "('assets/hotkey_icon.png', 'assets')" in spec
