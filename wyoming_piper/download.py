import json
import logging
import shutil
from pathlib import Path
from typing import Any, Dict, Iterable, Set, Tuple, Union
from urllib.error import URLError
from urllib.parse import quote, urlsplit, urlunsplit
from urllib.request import urlopen

from .file_hash import get_file_hash

# Change this to your Home Assistant share folder path
HASS_SHARE_DIR = Path("/config/share/piper_voices")

_DIR = Path(__file__).parent
_LOGGER = logging.getLogger(__name__)

_SKIP_FILES = {"MODEL_CARD"}

class VoiceNotFoundError(Exception):
    pass

def _quote_url(url: str) -> str:
    parts = list(urlsplit(url))
    parts[2] = quote(parts[2])
    return urlunsplit(parts)

def get_voices(
    download_dir: Union[str, Path], update_voices: bool = False
) -> Dict[str, Any]:
    download_dir = Path(download_dir)
    voices_download = download_dir / "voices.json"

    if update_voices:
        # Instead of downloading, we'll use a local voices.json file
        voices_local = HASS_SHARE_DIR / "voices.json"
        if voices_local.exists():
            shutil.copy(voices_local, voices_download)
            _LOGGER.info(f"Updated voices.json from {voices_local}")
        else:
            _LOGGER.warning(f"Local voices.json not found at {voices_local}")

    if voices_download.exists():
        try:
            _LOGGER.debug("Loading %s", voices_download)
            with open(voices_download, "r", encoding="utf-8") as voices_file:
                return json.load(voices_file)
        except Exception:
            _LOGGER.exception("Failed to load %s", voices_download)

    # Fall back to embedded
    voices_embedded = _DIR / "voices.json"
    _LOGGER.debug("Loading %s", voices_embedded)
    with open(voices_embedded, "r", encoding="utf-8") as voices_file:
        return json.load(voices_file)

def ensure_voice_exists(
    name: str,
    data_dirs: Iterable[Union[str, Path]],
    download_dir: Union[str, Path],
    voices_info: Dict[str, Any],
):
    if name not in voices_info:
        find_voice(name, data_dirs)
        return

    assert data_dirs, "No data dirs"

    voice_info = voices_info[name]
    voice_files = voice_info["files"]
    verified_files: Set[str] = set()
    files_to_copy: Set[str] = set()

    for data_dir in data_dirs:
        data_dir = Path(data_dir)

        for file_path, file_info in voice_files.items():
            if file_path in verified_files:
                continue

            file_name = Path(file_path).name
            if file_name in _SKIP_FILES:
                continue

            data_file_path = data_dir / file_name
            _LOGGER.debug("Checking %s", data_file_path)
            if not data_file_path.exists():
                _LOGGER.debug("Missing %s", data_file_path)
                files_to_copy.add(file_path)
                continue

            expected_size = file_info["size_bytes"]
            actual_size = data_file_path.stat().st_size
            if expected_size != actual_size:
                _LOGGER.warning(
                    "Wrong size (expected=%s, actual=%s) for %s",
                    expected_size,
                    actual_size,
                    data_file_path,
                )
                files_to_copy.add(file_path)
                continue

            expected_hash = file_info["md5_digest"]
            actual_hash = get_file_hash(data_file_path)
            if expected_hash != actual_hash:
                _LOGGER.warning(
                    "Wrong hash (expected=%s, actual=%s) for %s",
                    expected_hash,
                    actual_hash,
                    data_file_path,
                )
                files_to_copy.add(file_path)
                continue

            verified_files.add(file_path)
            files_to_copy.discard(file_path)

    if (not voice_files) and (not files_to_copy):
        raise ValueError(f"Unable to find or copy voice: {name}")

    try:
        download_dir = Path(download_dir)

        for file_path in files_to_copy:
            file_name = Path(file_path).name
            if file_name in _SKIP_FILES:
                continue

            source_file_path = HASS_SHARE_DIR / file_name
            dest_file_path = download_dir / file_name
            dest_file_path.parent.mkdir(parents=True, exist_ok=True)

            if source_file_path.exists():
                _LOGGER.debug("Copying %s to %s", source_file_path, dest_file_path)
                shutil.copy(source_file_path, dest_file_path)
                _LOGGER.info("Copied %s", dest_file_path)
            else:
                _LOGGER.warning(f"Source file not found: {source_file_path}")

    except Exception:
        _LOGGER.exception("Unexpected error while copying files for %s", name)

def find_voice(name: str, data_dirs: Iterable[Union[str, Path]]) -> Tuple[Path, Path]:
    for data_dir in data_dirs:
        data_dir = Path(data_dir)
        onnx_path = data_dir / f"{name}.onnx"
        config_path = data_dir / f"{name}.onnx.json"

        if onnx_path.exists() and config_path.exists():
            return onnx_path, config_path

    # Try as a custom voice
    onnx_path = Path(name)
    config_path = Path(name + ".json")

    if onnx_path.exists() and config_path.exists():
        return onnx_path, config_path

    raise VoiceNotFoundError(name)
