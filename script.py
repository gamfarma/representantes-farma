#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
script.py — GAM Farma | Gerador automatico do index.html
Le a planilha do Google Sheets (CSV publicado) e regenera o index.html.
Uso: python script.py
"""

import csv
import io
import re
import sys
import unicodedata
import urllib.request
import urllib.error
from datetime import datetime

CSV_URL = (
    "https://docs.google.com/spreadsheets/d/e/"
    "2PACX-1vQJRPejEYUGjqFiruPTGJuS2Itk6qjvyk6moB4_ChCe5_z4_CW0jYcYXJFimYYw4kGcbP2fpdRccLkq"
    "/pub?output=csv"
)
LOGO_URL = (
    "https://raw.githubusercontent.com/gamfarma/imagem-site/"
    "2091104c3fa6efcc97594176ed36b38218ffa0f2/Logo%20GAM%20Nova%20Branca.png"
)
OUTPUT_HTML = "index.html"
REFRESH_INTERVAL_MS = 5 * 60 * 1000

def _norm(s):
    """Normaliza string removendo acentos e convertendo para maiuscula."""
    return unicodedata.normalize("NFD", s or "").encode("ascii", "ignore").decode().upper().strip()


def _strip_col(h):
    """Sanitiza nomes de coluna."""
    s = _norm(h)
    s = s.replace("COORPORATIVO", "CORPORATIVO").replace("COODENADOR", "COORDENADOR")
    if s == "NOME REPRESENTANTE":
        s = "NOME"
    return s


def fetch_csv():
    """Baixa e parseia o CSV do Google Sheets."""
    ts = int(datetime.now().timestamp())
    full_url = f"{CSV_URL}&cb={ts}"
    req = urllib.request.Request(full_url, headers={
        "Cache-Control": "no-cache, no-store",
        "Pragma": "no-cache",
        "User-Agent": "Mozilla/5.0",
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8-sig")
    except urllib.error.URLError as e:
        print(f"[ERRO] Falha ao baixar CSV: {e}", file=sys.stderr)
        sys.exit(1)

    lines = raw.splitlines()
    header_idx = -1
    update_date = ""
    for i, line in enumerate(lines):
        upper = _norm(line)
        if "DISTRITO" in upper and ("NOME" in upper or "REPRESENTANTE" in upper):
            header_idx = i
            break
        m = re.search(r"\d{2}/\d{2}/\d{4}", line)
        if m:
            update_date = m.group(0)

    if header_idx == -1:
        print("[ERRO] Cabecalho nao encontrado no CSV.", file=sys.stderr)
        sys.exit(1)

    reader = csv.DictReader(io.StringIO("\n".join(lines[header_idx:])))
    rows = []
    for raw_row in reader:
        row = {_strip_col(k): (v or "").strip() for k, v in raw_row.items() if k}
        nome = row.get("NOME", "").strip()
        if not nome:
            continue
        rows.append(row)
    print(f"[OK] {len(rows)} registros. Data planilha: {update_date}")
    return rows, update_date


def _js_str(s):
    """Escapa string para embutir em JavaScript."""
    return (s or "").replace("\\", "\\\\").replace("'", "\\'").replace("\n", " ").replace("\r", "")


def rows_to_js(rows):
    """Converte rows para array JavaScript."""
    items = []
    for r in rows:
        fields = []
        for k, v in r.items():
            k_safe = k.replace('"', "").replace("'", "")
            v_safe = _js_str(v)
            fields.append(f"\'{k_safe}\':\'{v_safe}\'")
        items.append("{" + ",".join(fields) + "}")
    return "[\n" + ",\n".join(items) + "\n]"


def generate_html(rows, update_date):
    """Gera o HTML atualizado com dados embutidos."""
    now_str = datetime.now().strftime("%d/%m/%Y %H:%M")
    rows_js = rows_to_js(rows)

    with open(OUTPUT_HTML, "r", encoding="utf-8") as f:
        html_template = f.read()

    # Substituir dados embutidos
    import re as _re
    html_updated = _re.sub(
        r"const EMBEDDED_ROWS = \[.*?\];",
        f"const EMBEDDED_ROWS = {rows_js};",
        html_template,
        flags=_re.DOTALL
    )
    html_updated = _re.sub(
        r"const EMBEDDED_DATE = \'[^\']*\';",
        f"const EMBEDDED_DATE = \'{update_date}\';",
        html_updated
    )
    html_updated = _re.sub(
        r"<!-- GERADO EM: .*? -->",
        f"<!-- GERADO EM: {now_str} | DATA PLANILHA: {update_date} -->",
        html_updated
    )
    return html_updated


if __name__ == "__main__":
    print("=" * 50)
    print("GAM Farma - Gerador de index.html")
    print("=" * 50)
    print("[1/3] Baixando planilha do Google Sheets...")
    rows, update_date = fetch_csv()
    print(f"[2/3] Gerando {OUTPUT_HTML}...")
    html = generate_html(rows, update_date)
    with open(OUTPUT_HTML, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[OK] {OUTPUT_HTML} atualizado! ({len(html)} bytes)")
    print("=" * 50)
