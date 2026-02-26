#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path

from hora import __version__

VIDEO_EXTENSIONS = {
    ".mp4",
    ".m4v",
    ".mov",
    ".mkv",
    ".avi",
    ".wmv",
    ".flv",
    ".webm",
    ".mpeg",
    ".mpg",
    ".ts",
    ".m2ts",
    ".3gp",
}
MAIN_SELECTION_FILENAME = ".hora_main_selection.json"
MAIN_SELECTION_ROOT_KEY = "root_dir"
ANSI_ORANGE = "\033[38;5;208m"
ANSI_RESET = "\033[0m"
UPDATE_SKIP_ENV = "HORA_SKIP_UPDATE_CHECK"
UPDATE_DEBUG_ENV = "HORA_DEBUG_UPDATE_CHECK"
UPDATE_BRANCH = "main"
UPDATE_TIMEOUT_SECONDS = 2
UPDATE_COMMAND = "pipx upgrade hora"
DISTRIBUTION_NAME = "hora"


@dataclass
class VideoMetadata:
    duration_ms: int
    resolution: str
    fps: float | None


def duration_to_milliseconds(duration_text: str) -> int:
    match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", duration_text)
    if not match:
        raise ValueError("Duration konnte nicht aus ffmpeg-Ausgabe gelesen werden.")

    hours = int(match.group(1))
    minutes = int(match.group(2))
    seconds = float(match.group(3))
    total_seconds = hours * 3600 + minutes * 60 + seconds
    return int(total_seconds * 1000)


def run_ffmpeg_probe(video_path: Path) -> str:
    try:
        result = subprocess.run(
            ["ffmpeg", "-i", str(video_path)],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("ffmpeg wurde nicht gefunden. Bitte ffmpeg installieren.") from exc

    return f"{result.stdout}\n{result.stderr}"


def parse_fps_value(fps_text: str) -> float:
    if "/" in fps_text:
        numerator_text, denominator_text = fps_text.split("/", maxsplit=1)
        denominator = float(denominator_text)
        if denominator == 0:
            raise ValueError("FPS konnte nicht aus ffmpeg-Ausgabe gelesen werden.")
        return float(numerator_text) / denominator
    return float(fps_text)


def format_fps(fps: float | None) -> str:
    if fps is None:
        return "unbekannt"
    rounded = round(fps)
    if abs(fps - rounded) < 0.01:
        return str(int(rounded))
    return f"{fps:.3f}".rstrip("0").rstrip(".")


def orange_text(text: str) -> str:
    if not sys.stdout.isatty():
        return text
    return f"{ANSI_ORANGE}{text}{ANSI_RESET}"


def env_flag(name: str) -> bool:
    value = os.getenv(name, "").strip().lower()
    return value in {"1", "true", "yes", "y", "on"}


def debug_update_check(message: str) -> None:
    if env_flag(UPDATE_DEBUG_ENV):
        print(f"[update-check] {message}", file=sys.stderr)


def get_install_source_from_direct_url() -> tuple[str, str] | None:
    try:
        dist = metadata.distribution(DISTRIBUTION_NAME)
    except metadata.PackageNotFoundError:
        return None

    direct_url_text = dist.read_text("direct_url.json")
    if not direct_url_text:
        return None

    try:
        direct_url_data = json.loads(direct_url_text)
    except json.JSONDecodeError:
        return None

    repo_url = direct_url_data.get("url")
    vcs_info = direct_url_data.get("vcs_info")
    if not isinstance(repo_url, str) or not isinstance(vcs_info, dict):
        return None

    commit_id = vcs_info.get("commit_id")
    if not isinstance(commit_id, str) or not commit_id:
        return None

    if repo_url.startswith("git+"):
        repo_url = repo_url[4:]

    return repo_url, commit_id


def get_remote_branch_commit(repo_url: str, branch: str) -> str:
    try:
        result = subprocess.run(
            ["git", "ls-remote", repo_url, f"refs/heads/{branch}"],
            capture_output=True,
            text=True,
            check=False,
            timeout=UPDATE_TIMEOUT_SECONDS,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("git wurde nicht gefunden.") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("Update-Check Timeout.") from exc

    if result.returncode != 0:
        stderr = result.stderr.strip()
        raise RuntimeError(stderr if stderr else "git ls-remote fehlgeschlagen.")

    first_line = result.stdout.strip().splitlines()
    if not first_line:
        raise RuntimeError("Kein Commit von Remote erhalten.")

    fields = first_line[0].split()
    if not fields:
        raise RuntimeError("Ungültige Remote-Antwort.")

    return fields[0]


def short_commit(commit: str) -> str:
    return commit[:7]


def check_for_updates(skip_requested: bool) -> None:
    if skip_requested or env_flag(UPDATE_SKIP_ENV):
        return

    source = get_install_source_from_direct_url()
    if source is None:
        return

    repo_url, local_commit = source

    try:
        remote_commit = get_remote_branch_commit(repo_url, UPDATE_BRANCH)
    except RuntimeError as err:
        debug_update_check(str(err))
        return

    if remote_commit == local_commit:
        return

    print(
        orange_text(
            "WARNUNG: Ein neuer Stand auf 'main' ist verfügbar "
            f"(lokal {short_commit(local_commit)} -> remote {short_commit(remote_commit)})."
        )
    )
    print(orange_text(f"Update ausführen mit: {UPDATE_COMMAND}"))


def prompt_continue_after_duration_warning() -> bool:
    while True:
        choice = input("Trotzdem fortfahren? (j/n): ").strip().lower()
        if choice in {"j", "ja", "y", "yes"}:
            return True
        if choice in {"n", "nein", "no"}:
            return False
        print("Ungültige Eingabe. Bitte 'j' oder 'n' eingeben.")


def check_duration_consistency(
    metadata_by_path: dict[Path, VideoMetadata], root: Path
) -> bool:
    groups: dict[int, list[Path]] = {}
    for path, metadata_obj in metadata_by_path.items():
        groups.setdefault(metadata_obj.duration_ms, []).append(path)

    if len(groups) <= 1:
        print("Alle Videos haben dieselbe Länge.")
        return True

    print(orange_text("WARNUNG: Nicht alle Videos haben dieselbe Länge."))
    for duration_ms in sorted(groups):
        rel_paths = ", ".join(
            str(video_path.relative_to(root)) for video_path in groups[duration_ms]
        )
        print(orange_text(f"- {duration_ms} ms: {rel_paths}"))

    try:
        return prompt_continue_after_duration_warning()
    except EOFError:
        return False


def build_video_mode(metadata_obj: VideoMetadata) -> str:
    if metadata_obj.resolution == "unbekannt":
        raise ValueError("VideoMode konnte nicht erstellt werden (Auflösung unbekannt).")
    if metadata_obj.fps is None:
        raise ValueError("VideoMode konnte nicht erstellt werden (FPS unbekannt).")
    return f"{metadata_obj.resolution}x{format_fps(metadata_obj.fps)}"


def generate_master_autorun_content(main_file: Path, main_metadata: VideoMetadata) -> str:
    video_mode = build_video_mode(main_metadata)
    return (
        "'   __  __           _____ _______ ______ _____  \n"
        "'  |  \\/  |   /\\    / ____|__   __|  ____|  __ \\ \n"
        "'  | \\  / |  /  \\  | (___    | |  | |__  | |__) |\n"
        "'  | |\\/| | / /\\ \\  \\___ \\   | |  |  __| |  _  / \n"
        "'  | |  | |/ ____ \\ ____) |  | |  | |____| | \\ \\ \n"
        "'  |_|  |_/_/    \\_\\_____/   |_|  |______|_|  \\_\\\n"
        "'                                               \n"
        "' BrightSign Master Sync Script - Term7 Loop Version\n"
        "\n"
        f'videoFile = "{main_file.name}"\n'
        f"videoDurationMs = {main_metadata.duration_ms}\n"
        f'VideoMode = "{video_mode}"\n'
        "ScaleMode = 2\n"
        "audioVolume = 20\n"
        "\n"
        "' ---- SETUP NETWORK ----\n"
        'nc = CreateObject("roNetworkConfiguration", 0)\n'
        'nc.SetIP4Address("192.168.1.10")\n'
        'nc.SetIP4Netmask("255.255.255.0")\n'
        'nc.SetIP4Broadcast("192.168.1.255")\n'
        'nc.SetIP4Gateway("192.168.1.1")\n'
        "nc.Apply()\n"
        "\n"
        "' ---- SETUP UDP SENDER ----\n"
        'sender = CreateObject("roDatagramSender")\n'
        'sender.SetDestination("192.168.1.255", 11167)\n'
        "\n"
        "' ---- SETUP VIDEO PLAYER ----\n"
        'mode = CreateObject("roVideoMode")\n'
        "mode.SetMode(VideoMode)\n"
        "\n"
        'v = CreateObject("roVideoPlayer")\n'
        'p = CreateObject("roMessagePort")\n'
        "v.SetPort(p)\n"
        "v.SetViewMode(ScaleMode)\n"
        "v.SetVolume(audioVolume)\n"
        "v.SetLoopMode(false)\n"
        "\n"
        'aa = CreateObject("roAssociativeArray")\n'
        "aa.Filename = videoFile\n"
        "\n"
        "' ---- SYNC LOOP ----\n"
        "sleep(10000)\n"
        "\n"
        "while true\n"
        '    sender.Send("ply")\n'
        "    v.PlayFile(aa)\n"
        "\n"
        "    sleep(videoDurationMs)\n"
        "\n"
        '    sender.Send("pre")\n'
        "    v.PreloadFile(videoFile)\n"
        "\n"
        "    sleep(50)\n"
        "end while\n"
    )


def generate_client_autorun_content(
    video_file_name: str, video_mode: str, client_id: int
) -> str:
    client_ip = f"192.168.1.{10 + client_id}"
    return (
        "'    _____ _      _____ ______ _   _ _______    ___\n"
        "'   / ____| |    |_   _|  ____| \\ | |__   __|  |__ \\\n"
        "'  | |    | |      | | | |__  |  \\| |  | |        ) |\n"
        "'  | |    | |      | | |  __| | . ` |  | |       / /\n"
        "'  | |____| |____ _| |_| |____| |\\  |  | |      / /_\n"
        "'   \\_____|______|_____|______|_| \\_|  |_|     |____|\n"
        "'                                                  \n"
        "' BrightSign Client Sync Script - Term7 Loop Version\n"
        "\n"
        f'videoFile = "{video_file_name}"\n'
        f'VideoMode = "{video_mode}"\n'
        "ScaleMode = 2\n"
        "audioVolume = 20\n"
        f'ClientIP = "{client_ip}"  \' Change this per device\n'
        "\n"
        "' ---- SETUP NETWORK ----\n"
        'nc = CreateObject("roNetworkConfiguration", 0)\n'
        "nc.SetIP4Address(ClientIP)\n"
        'nc.SetIP4Netmask("255.255.255.0")\n'
        'nc.SetIP4Broadcast("192.168.1.255")\n'
        'nc.SetIP4Gateway("192.168.1.1")\n'
        "nc.Apply()\n"
        "\n"
        "' ---- SETUP VIDEO PLAYER ----\n"
        'mode = CreateObject("roVideoMode")\n'
        "mode.SetMode(VideoMode)\n"
        "\n"
        'v = CreateObject("roVideoPlayer")\n'
        "v.SetViewMode(ScaleMode)\n"
        "v.SetVolume(audioVolume)\n"
        "v.SetLoopMode(false)\n"
        "\n"
        "' ---- SETUP UDP RECEIVER ----\n"
        'receiver = CreateObject("roDatagramReceiver", 11167)\n'
        'p = CreateObject("roMessagePort")\n'
        "receiver.SetPort(p)\n"
        "\n"
        'preloadAA = CreateObject("roAssociativeArray")\n'
        "preloadAA.Filename = videoFile\n"
        "\n"
        "' ---- MAIN LISTEN LOOP ----\n"
        "listen:\n"
        "    msg = wait(2000, p)\n"
        "\n"
        '    if type(msg) = "roDatagramEvent" then\n'
        "        command = left(msg, 3)\n"
        "\n"
        '        if command = "pre" then\n'
        "            v.PreloadFile(videoFile)\n"
        '        elseif command = "ply" then\n'
        "            v.PlayFile(preloadAA)\n"
        "        endif\n"
        "    endif\n"
        "\n"
        "    goto listen\n"
    )


def create_main_autorun(
    root: Path, main_file: Path, main_metadata: VideoMetadata
) -> Path:
    content = generate_master_autorun_content(main_file, main_metadata)

    target_path = main_file.parent / "autorun.brs"
    try:
        target_path.write_text(content, encoding="utf-8")
    except OSError as exc:
        raise RuntimeError(f"autorun.brs konnte nicht geschrieben werden: {target_path}") from exc
    return target_path


def create_client_autorun(
    video_file: Path, video_metadata: VideoMetadata, client_id: int
) -> Path:
    video_mode = build_video_mode(video_metadata)
    content = generate_client_autorun_content(video_file.name, video_mode, client_id)

    target_path = video_file.parent / "autorun.brs"
    try:
        target_path.write_text(content, encoding="utf-8")
    except OSError as exc:
        raise RuntimeError(f"autorun.brs konnte nicht geschrieben werden: {target_path}") from exc
    return target_path


def parse_video_metadata(probe_output: str) -> VideoMetadata:
    duration_ms = duration_to_milliseconds(probe_output)

    video_line = None
    for line in probe_output.splitlines():
        if "Video:" in line:
            video_line = line
            break
    if video_line is None:
        raise ValueError("Video-Stream konnte nicht aus ffmpeg-Ausgabe gelesen werden.")

    resolution_match = re.search(r"\b(\d{2,5})x(\d{2,5})\b", video_line)
    if resolution_match:
        resolution = f"{resolution_match.group(1)}x{resolution_match.group(2)}"
    else:
        resolution = "unbekannt"

    fps_value = None
    fps_match = re.search(r"\b(\d+(?:\.\d+)?(?:/\d+(?:\.\d+)?)?)\s*fps\b", video_line)
    if fps_match is None:
        fps_match = re.search(r"\b(\d+(?:\.\d+)?(?:/\d+(?:\.\d+)?)?)\s*tbr\b", video_line)
    if fps_match is not None:
        fps_value = parse_fps_value(fps_match.group(1))

    return VideoMetadata(duration_ms=duration_ms, resolution=resolution, fps=fps_value)


def get_video_metadata(video_path: Path) -> VideoMetadata:
    probe_output = run_ffmpeg_probe(video_path)
    return parse_video_metadata(probe_output)


def find_video_files(root: Path) -> list[Path]:
    return sorted(
        path
        for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS
    )


def enforce_subfolder_limit(root: Path, max_subfolders: int = 10) -> None:
    subfolder_count = sum(1 for entry in root.iterdir() if entry.is_dir())
    if subfolder_count > max_subfolders:
        raise RuntimeError(
            f"Abbruch: {subfolder_count} Unterordner gefunden (maximal erlaubt: {max_subfolders})."
        )


def load_main_selection(root: Path) -> Path | None:
    selection_file = root / MAIN_SELECTION_FILENAME
    if not selection_file.exists():
        return None

    try:
        data = json.loads(selection_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None

    saved_root_dir = data.get(MAIN_SELECTION_ROOT_KEY)
    if not isinstance(saved_root_dir, str):
        return None
    if saved_root_dir != str(root.resolve()):
        return None

    main_rel_path = data.get("main")
    if not isinstance(main_rel_path, str) or not main_rel_path.strip():
        return None

    main_path = root / main_rel_path
    if not main_path.exists():
        return None
    if not main_path.resolve().is_relative_to(root.resolve()):
        return None
    return main_path


def save_main_selection(root: Path, main_path: Path) -> None:
    selection_file = root / MAIN_SELECTION_FILENAME
    payload = {
        MAIN_SELECTION_ROOT_KEY: str(root.resolve()),
        "main": str(main_path.relative_to(root)),
    }
    selection_file.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def prompt_main_selection(matches: list[Path], current_main: Path | None) -> Path:
    index_by_path = {path: idx for idx, path in enumerate(matches, start=1)}
    default_index = index_by_path.get(current_main) if current_main else None

    while True:
        if default_index:
            choice = input(
                f"Main-Datei wählen (1-{len(matches)}, Enter für {default_index}): "
            ).strip()
            if choice == "":
                return matches[default_index - 1]
        else:
            choice = input(f"Main-Datei wählen (1-{len(matches)}): ").strip()

        if not choice.isdigit():
            print("Ungültige Eingabe. Bitte eine Zahl eingeben.")
            continue

        selected_index = int(choice)
        if 1 <= selected_index <= len(matches):
            return matches[selected_index - 1]

        print(f"Ungültige Eingabe. Bitte eine Zahl zwischen 1 und {len(matches)} eingeben.")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="hora",
        description="Findet Videos, wählt ein Main-Video und generiert BrightSign autorun.brs Dateien.",
    )
    parser.add_argument(
        "--skip-update-check",
        action="store_true",
        help=(
            "Überspringt den Start-Update-Check. Alternativ via "
            f"{UPDATE_SKIP_ENV}=1 möglich."
        ),
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    return parser.parse_args(argv)


def _main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    check_for_updates(skip_requested=args.skip_update_check)

    root = Path.cwd()
    try:
        enforce_subfolder_limit(root)
    except RuntimeError as err:
        print(err)
        sys.exit(1)

    matches = find_video_files(root)

    if not matches:
        print("Keine Video-Dateien gefunden.")
        return

    current_main = load_main_selection(root)

    print(f"Schritt 1: Gefundene Video-Dateien in: {root}")
    for index, path in enumerate(matches, start=1):
        rel_path = path.relative_to(root)
        main_marker = " [Main]" if current_main == path else ""
        print(f"{index}. {rel_path}{main_marker}")

    try:
        main_file = prompt_main_selection(matches, current_main)
    except EOFError:
        if current_main:
            main_file = current_main
            print(
                f"Keine Eingabe möglich, bestehende Main-Auswahl bleibt: {main_file.relative_to(root)}"
            )
        else:
            main_file = matches[0]
            print(
                f"Keine Eingabe möglich, erste Datei wird als Main gesetzt: {main_file.relative_to(root)}"
            )

    save_main_selection(root, main_file)
    print(f"Gespeichert als Main: {main_file.relative_to(root)}")

    print("\nSchritt 2: Video-Metadaten")
    metadata_by_path: dict[Path, VideoMetadata] = {}
    for index, path in enumerate(matches, start=1):
        rel_path = path.relative_to(root)
        main_marker = " [Main]" if main_file == path else ""
        try:
            metadata_obj = get_video_metadata(path)
            metadata_by_path[path] = metadata_obj
            fps_text = format_fps(metadata_obj.fps)
            print(
                f"{index}. {rel_path}: {metadata_obj.duration_ms} ms, "
                f"{metadata_obj.resolution}, {fps_text} fps{main_marker}"
            )
        except (RuntimeError, ValueError) as err:
            print(f"{index}. {rel_path}: Fehler ({err}){main_marker}")

    if metadata_by_path and not check_duration_consistency(metadata_by_path, root):
        print("Abbruch auf Benutzerwunsch.")
        sys.exit(1)

    main_metadata = metadata_by_path.get(main_file)
    if main_metadata is None:
        print(
            f"Abbruch: Für die Main-Datei {main_file.relative_to(root)} konnten keine Metadaten gelesen werden."
        )
        sys.exit(1)

    try:
        target_autorun = create_main_autorun(root, main_file, main_metadata)
    except (RuntimeError, ValueError) as err:
        print(f"Abbruch: {err}")
        sys.exit(1)

    print(f"Main: autorun.brs geschrieben: {target_autorun.relative_to(root)}")

    client_id = 1
    for path in matches:
        if path == main_file:
            continue

        metadata_obj = metadata_by_path.get(path)
        if metadata_obj is None:
            print(
                f"Abbruch: Für Client-Datei {path.relative_to(root)} konnten keine Metadaten gelesen werden."
            )
            sys.exit(1)

        try:
            client_autorun = create_client_autorun(path, metadata_obj, client_id)
        except (RuntimeError, ValueError) as err:
            print(f"Abbruch: {err}")
            sys.exit(1)

        print(f"Client {client_id}: autorun.brs geschrieben: {client_autorun.relative_to(root)}")
        client_id += 1


def main(argv: list[str] | None = None) -> None:
    try:
        _main(argv)
    except KeyboardInterrupt:
        print("\nAbbruch durch Benutzer (Ctrl+C).")
        sys.exit(130)


if __name__ == "__main__":
    main()
