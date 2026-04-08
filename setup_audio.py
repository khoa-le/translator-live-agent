"""
setup_audio.py — Check and guide BlackHole virtual audio setup for meeting translation.

BlackHole is a free macOS virtual audio driver that creates loopback devices.
We need it to route meeting audio through the translation agent:

  Meeting app (Zoom/Teams) speaker → BlackHole → Agent → BlackHole → Meeting app mic
                                                       ↘ Your speakers (so you hear translation)

Run: python setup_audio.py
"""

import subprocess
import sys
import shutil


def check_blackhole():
    """Check if BlackHole is installed."""
    hal_path = "/Library/Audio/Plug-Ins/HAL"
    try:
        items = subprocess.run(
            ["ls", hal_path], capture_output=True, text=True
        )
        has_bh2 = "BlackHole2ch" in items.stdout or "BlackHole 2ch" in items.stdout
        has_bh16 = "BlackHole16ch" in items.stdout or "BlackHole 16ch" in items.stdout
    except Exception:
        has_bh2 = False
        has_bh16 = False

    return has_bh2, has_bh16


def list_audio_devices():
    """List all audio devices via sounddevice."""
    try:
        import sounddevice as sd
        devices = sd.query_devices()
        print("\nAudio devices:")
        print("-" * 70)
        for i, d in enumerate(devices):
            direction = ""
            if d["max_input_channels"] > 0 and d["max_output_channels"] > 0:
                direction = "IN/OUT"
            elif d["max_input_channels"] > 0:
                direction = "IN"
            elif d["max_output_channels"] > 0:
                direction = "OUT"
            print(f"  {i:2d}: {d['name']:40s}  {direction}")
        print()
        return devices
    except ImportError:
        print("sounddevice not installed")
        return []


def main():
    print("=" * 60)
    print("  Meeting Translation — Audio Setup Check")
    print("=" * 60)

    # Check BlackHole
    has_bh2, has_bh16 = check_blackhole()

    if has_bh2 or has_bh16:
        print("\n[OK] BlackHole is installed:")
        if has_bh2:
            print("  - BlackHole 2ch")
        if has_bh16:
            print("  - BlackHole 16ch")
    else:
        print("\n[MISSING] BlackHole is not installed.")
        print()
        print("Install with Homebrew:")
        print("  brew install blackhole-2ch")
        print()
        print("Or download from: https://existential.audio/blackhole/")
        print()
        print("After installing, restart this script.")

        if shutil.which("brew"):
            answer = input("\nInstall BlackHole 2ch now via Homebrew? [y/N] ")
            if answer.lower() == "y":
                print("\nInstalling BlackHole 2ch...")
                result = subprocess.run(
                    ["brew", "install", "blackhole-2ch"],
                    capture_output=False,
                )
                if result.returncode == 0:
                    print("\n[OK] BlackHole 2ch installed!")
                    print("You may need to restart your Mac or log out/in.")
                    has_bh2 = True
                else:
                    print("\n[ERROR] Installation failed.")
                    sys.exit(1)
            else:
                sys.exit(0)
        else:
            sys.exit(0)

    # List devices
    devices = list_audio_devices()

    # Find BlackHole devices
    bh_devices = [
        (i, d) for i, d in enumerate(devices)
        if "blackhole" in d["name"].lower()
    ]

    if not bh_devices:
        print("[WARNING] BlackHole installed but not showing in audio devices.")
        print("Try restarting your Mac or logging out and back in.")
        sys.exit(1)

    # Setup instructions
    print("=" * 60)
    print("  Setup Instructions")
    print("=" * 60)
    print()
    print("Step 1: Create a Multi-Output Device (one-time)")
    print("  - Open: /Applications/Utilities/Audio MIDI Setup.app")
    print('  - Click "+" at bottom-left → "Create Multi-Output Device"')
    print("  - Check these outputs:")
    print("    [x] BlackHole 2ch")
    print("    [x] Your speakers (e.g. Mac mini Speakers or LG ULTRAFINE)")
    print('  - Rename it to "Translation Output" (right-click → rename)')
    print()
    print("Step 2: Configure your meeting app (Zoom/Teams/Discord)")
    print("  - Speaker/Output → BlackHole 2ch")
    print("    (this sends meeting audio to the agent)")
    print("  - Microphone/Input → BlackHole 2ch")
    print("    (this receives translated audio from the agent)")
    print()
    print("Step 3: Run the translation agent")
    print("  python agent.py console \\")

    # Find BlackHole input/output device IDs
    bh_input = None
    bh_output = None
    for i, d in bh_devices:
        if d["max_input_channels"] > 0:
            bh_input = i
        if d["max_output_channels"] > 0:
            bh_output = i

    if bh_input is not None and bh_output is not None:
        print(f"    --input-device {bh_input} \\")
        print(f"    --output-device {bh_output}")
    else:
        print('    --input-device "BlackHole" \\')
        print('    --output-device "BlackHole"')

    print()
    print("Step 4: Set your Mac system output")
    print('  System Settings → Sound → Output → "Translation Output"')
    print("  (so you hear BOTH the original meeting + translated audio)")
    print()
    print("=" * 60)
    print()
    print("Audio flow:")
    print("  Meeting speaker → BlackHole → Agent (translate) → BlackHole → Meeting mic")
    print("                                      ↘ Your speakers (via Multi-Output)")
    print()


if __name__ == "__main__":
    main()
