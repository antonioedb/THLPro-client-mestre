from __future__ import annotations

import subprocess
import sys

CMD = [
    sys.executable,
    "-m",
    "PyInstaller",
    "--onefile",
    "--noconsole",
    "--name",
    "THLProClient",
    "--collect-all",
    "pystray",
    "thlpro_client/__main__.py",
]

if __name__ == "__main__":
    subprocess.check_call(CMD)
    print("Build concluído. Arquivo em dist/THLProClient.exe")
