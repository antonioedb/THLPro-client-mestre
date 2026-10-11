from __future__ import annotations

import tkinter as tk
from tkinter import messagebox

from thlpro_client.config import ClientConfig


class ConfigWindow:
    def __init__(self, config: ClientConfig, on_save):
        self.config = config
        self.on_save = on_save
        self.root = tk.Tk()
        self.root.title("THLPro Cliente - Configurações")
        self.root.geometry("520x280")

        self.server_var = tk.StringVar(value=config.server_url)
        self.email_var = tk.StringVar(value=config.email)
        self.password_var = tk.StringVar(value="")
        self.client_name_var = tk.StringVar(value=config.client_name)
        self.computer_name_var = tk.StringVar(value=config.computer_name)
        self.simulate_var = tk.BooleanVar(value=config.simulate)

        self._build()

    def _build(self):
        fields = [
            ("URL do servidor", self.server_var),
            ("E-mail", self.email_var),
            ("Senha (não armazenada)", self.password_var),
            ("Nome do cliente", self.client_name_var),
            ("Nome do computador", self.computer_name_var),
        ]
        for i, (label, var) in enumerate(fields):
            tk.Label(self.root, text=label).grid(row=i, column=0, sticky="w", padx=8, pady=6)
            ent = tk.Entry(self.root, textvariable=var, width=45, show="*" if "Senha" in label else "")
            ent.grid(row=i, column=1, padx=8, pady=6)

        tk.Checkbutton(self.root, text="Modo simulação (desenvolvimento)", variable=self.simulate_var).grid(
            row=5, column=1, sticky="w", padx=8, pady=8
        )

        tk.Button(self.root, text="Salvar e iniciar", command=self._save).grid(row=6, column=1, sticky="e", padx=8, pady=12)

    def _save(self):
        if not self.server_var.get().strip() or not self.email_var.get().strip():
            messagebox.showerror("Configuração", "Preencha URL do servidor e e-mail.")
            return
        self.config.server_url = self.server_var.get().strip()
        self.config.email = self.email_var.get().strip()
        self.config.client_name = self.client_name_var.get().strip() or "THLPro Local"
        self.config.computer_name = self.computer_name_var.get().strip()
        self.config.simulate = self.simulate_var.get()
        self.on_save(self.config, self.password_var.get())
        self.root.destroy()

    def run(self):
        self.root.mainloop()
