from thlpro_client.logger import configure_logging
from thlpro_client.rtd_client import ExcelBridgeRTDClient
from thlpro_client.app_paths import ensure_app_dirs
import time

paths = ensure_app_dirs()
logger = configure_logging(str(paths["logs"] / "teste_rtd2.log"))

client = ExcelBridgeRTDClient(logger)

client.connect()
client.register_meta(1, "ABEVA100")
client.subscribe("ABEVA100", ["ULT", "OCP", "OVD"])

for i in range(10):
    time.sleep(2)

    ws = client._ws
    last = client._row - 1

    print(f"--- leitura {i + 1} ---")
    print("última linha:", last)

    for row in range(1, last + 1):
        cell = ws.Range(f"A{row}")
        print(f"A{row}: Value={cell.Value!r} | Text={cell.Text!r}")

client.close()