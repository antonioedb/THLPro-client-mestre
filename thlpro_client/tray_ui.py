from __future__ import annotations

import logging

try:
    import pystray
    from PIL import Image, ImageDraw
except Exception:  # pragma: no cover
    pystray = None
    Image = None
    ImageDraw = None


class TrayApp:
    def __init__(self, logger: logging.Logger, on_open, on_toggle_capture, on_exit):
        self.logger = logger
        self.on_open = on_open
        self.on_toggle_capture = on_toggle_capture
        self.on_exit = on_exit
        self.icon = None
        self.running = False

    def _create_icon(self):
        image = Image.new("RGB", (64, 64), (30, 30, 30))
        draw = ImageDraw.Draw(image)
        draw.rectangle((8, 8, 56, 56), outline=(0, 180, 90), width=4)
        draw.text((18, 22), "TH", fill=(230, 230, 230))
        return image

    def run(self):
        if not pystray:
            self.logger.warning("pystray indisponível neste ambiente; executando sem bandeja.")
            return
        self.running = True
        menu = pystray.Menu(
            pystray.MenuItem("Abrir", lambda _: self.on_open()),
            pystray.MenuItem("Iniciar/Parar captura", lambda _: self.on_toggle_capture()),
            pystray.MenuItem("Sair", lambda _: self._exit()),
        )
        self.icon = pystray.Icon("THLPro", self._create_icon(), "THLPro Cliente", menu)
        self.icon.run()

    def _exit(self):
        self.running = False
        self.on_exit()
        if self.icon:
            self.icon.stop()
