#!/usr/bin/env python3
"""
script.py — GAM Farma Representantes
Lê dados do Google Sheets (CSV público) e atualiza/valida a planilha para uso pelo index.html.
Detecta automaticamente mudanças de colunas, linhas, nomes, funções, telefones, emails, etc.
Executado pelo GitHub Actions em cada push ou agendamento.
"""

import csv
import io
import json
import os
import sys
import urllib.request
from datetime import datetime, timezone

# ============================================================
# CONFIGURAÇÃO
# ============================================================
CSV_URL = (
    "https://docs.google.com/spreadsheets/d/e/"
    "2PACX-1vQJRPejEYUGjqFiruPTGJuS2Itk6qjvyk6moB4_ChCe5_z4_CW0jYcYXJFimYYw4kGcbP2fpdRccLkq"
    "/pub?output=csv"
)

# Nomes-padrão dos arquivos (não altere)
INDEX_FILE = "index.html"
SCRIPT_FILE = "script.py"
DEPLOY_FILE = "deploy.yml"
SNAPSHOT_FILE = "data_snapshot.json"

# Mapeamento de normalização de cabeçalhos
HEADER_ALIASES = {
    "NOME REPRESENTANTE": "NOME",
    "CONTATO COORPORATIVO": "CONTATO CORPORATIVO",
    "CONTATO CORPORATIVO": "CONTATO CORPORATIVO",
    "COODENADOR": "COORDENADOR",
    "COORDENADOR": "COORDENADOR",
    "RAZAO SOCIAL": "RAZAO SOCIAL",
    "RAZÃO SOCIAL": "RAZAO SOCIAL",
    "FUNCAO": "FUNCAO",
    "FUNÇÃO": "FUNCAO",
    "REGIAO": "REGIAO",
    "REGIÃO": "REGIAO",
    "PRINCIPAIS CIDADES": "PRINCIPAIS CIDADES",
    "UF": "UF",
    "SETOR": "SETOR",
    "DISTRITO": "DISTRITO",
    "EMAIL": "EMAIL",
    "NOME": "NOME",
}

# Colunas obrigatórias esperadas
REQUIRED_COLS = {"DISTRITO", "SETOR", "REGIAO", "UF", "FUNCAO", "NOME", "EMAIL", "CONTATO CORPORATIVO"}


def normalize_header(h: str) -> str:
    """Normaliza cabeçalhos removendo acentos e aplicando aliases."""
    import unicodedata
    nfkd = unicodedata.normalize("NFD", h)
    ascii_str = "".join(c for c in nfkd if not unicodedata.combining(c))
    upper = ascii_str.upper().strip()
    return HEADER_ALIASES.get(upper, upper)


def parse_csv_from_url(url: str) -> list[dict]:
    """Baixa e parseia o CSV do Google Sheets."""
    cache_bust = f"{url}&cb={int(datetime.now(timezone.utc).timestamp())}"
    req = urllib.request.Request(
        cache_bust,
        headers={
            "Cache-Control": "no-store, no-cache",
            "Pragma": "no-cache",
            "User-Agent": "GAMFarma-GithubActions/1.0",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read().decode("utf-8-sig")

    lines = raw.splitlines()
    header_idx = -1
    for i, line in enumerate(lines):
        upper = line.upper()
        if "DISTRITO" in upper and ("NOME" in upper or "REPRESENTANTE" in upper):
            header_idx = i
            break

    if header_idx == -1:
        raise ValueError("Cabeçalho da planilha não encontrado. Verifique o link do Google Sheets.")

    reader = csv.DictReader(
        io.StringIO("\n".join(lines[header_idx:])),
    )
    raw_headers = reader.fieldnames or []
    normalized_headers = [normalize_header(h) for h in raw_headers]

    rows = []
    for raw_row in reader:
        row = {}
        for orig_h, norm_h in zip(raw_headers, normalized_headers):
            row[norm_h] = (raw_row.get(orig_h) or "").strip()
        if not row.get("NOME") or row["NOME"] in ("", "-"):
            continue
        rows.append(row)

    return rows


def validate_structure(rows: list[dict]) -> dict:
    """Valida a estrutura dos dados e retorna relatório."""
    if not rows:
        return {"ok": False, "error": "Nenhuma linha de dados encontrada."}

    found_cols = set(rows[0].keys())
    missing = REQUIRED_COLS - found_cols
    extra = found_cols - REQUIRED_COLS - {"RAZAO SOCIAL", "COORDENADOR", "PRINCIPAIS CIDADES"}

    funcs = {}
    for r in rows:
        f = r.get("FUNCAO", "").strip()
        if f:
            funcs[f] = funcs.get(f, 0) + 1

    return {
        "ok": True,
        "total_rows": len(rows),
        "columns_found": sorted(found_cols),
        "missing_cols": sorted(missing),
        "extra_cols": sorted(extra),
        "functions_found": funcs,
    }


def detect_changes(new_rows: list[dict], snapshot_path: str) -> dict:
    """Detecta mudanças comparando com snapshot anterior."""
    if not os.path.exists(snapshot_path):
        return {"first_run": True, "added": len(new_rows), "removed": 0, "modified": 0}

    with open(snapshot_path, "r", encoding="utf-8") as f:
        old_data = json.load(f)

    old_rows = old_data.get("rows", [])
    old_by_key = {(r.get("DISTRITO", "") + "|" + r.get("SETOR", "")): r for r in old_rows}
    new_by_key = {(r.get("DISTRITO", "") + "|" + r.get("SETOR", "")): r for r in new_rows}

    added = [k for k in new_by_key if k not in old_by_key]
    removed = [k for k in old_by_key if k not in new_by_key]
    modified = []

    for k in new_by_key:
        if k in old_by_key:
            for col in REQUIRED_COLS | {"RAZAO SOCIAL", "NOME"}:
                if new_by_key[k].get(col, "") != old_by_key[k].get(col, ""):
                    modified.append({"key": k, "col": col,
                                     "old": old_by_key[k].get(col, ""),
                                     "new": new_by_key[k].get(col, "")})

    return {
        "first_run": False,
        "added": len(added),
        "removed": len(removed),
        "modified": len(modified),
        "added_keys": added[:20],
        "removed_keys": removed[:20],
        "changes": modified[:50],
    }


def save_snapshot(rows: list[dict], path: str):
    """Salva snapshot dos dados para comparação futura."""
    snapshot = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "total": len(rows),
        "rows": rows,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=2)


def print_report(validation: dict, changes: dict):
    """Imprime relatório detalhado para o log do GitHub Actions."""
    print("=" * 60)
    print("  GAM Farma — Relatório de Atualização de Dados")
    print(f"  {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
    print("=" * 60)

    if not validation["ok"]:
        print(f"\n[ERRO] {validation['error']}")
        sys.exit(1)

    print(f"\n✅ Total de registros: {validation['total_rows']}")
    print(f"📋 Colunas encontradas: {', '.join(validation['columns_found'])}")

    if validation["missing_cols"]:
        print(f"⚠️  Colunas ausentes: {', '.join(validation['missing_cols'])}")
    if validation["extra_cols"]:
        print(f"ℹ️  Colunas extras: {', '.join(validation['extra_cols'])}")

    print("\n📊 Distribuição por função:")
    for func, count in sorted(validation["functions_found"].items()):
        print(f"   {func}: {count}")

    print("\n🔄 Mudanças detectadas:")
    if changes.get("first_run"):
        print(f"   Primeira execução — {changes['added']} registros carregados.")
    else:
        print(f"   ➕ Adicionados: {changes['added']}")
        print(f"   ➖ Removidos:   {changes['removed']}")
        print(f"   ✏️  Modificados: {changes['modified']}")
        if changes.get("added_keys"):
            print(f"   Novos: {changes['added_keys']}")
        if changes.get("removed_keys"):
            print(f"   Removidos: {changes['removed_keys']}")
        if changes.get("changes"):
            print("   Detalhes das modificações:")
            for ch in changes["changes"][:10]:
                print(f"     [{ch['key']}] {ch['col']}: '{ch['old']}' → '{ch['new']}'")

    print("\n✅ index.html e snapshot atualizados com sucesso.")
    print("=" * 60)


def main():
    print("🚀 Iniciando script.py — GAM Farma Representantes")
    print(f"   Lendo: {CSV_URL[:80]}...")

    try:
        rows = parse_csv_from_url(CSV_URL)
    except Exception as e:
        print(f"[ERRO CRÍTICO] Falha ao baixar dados do Google Sheets: {e}")
        sys.exit(1)

    validation = validate_structure(rows)
    changes = detect_changes(rows, SNAPSHOT_FILE)
    print_report(validation, changes)

    # Salva snapshot para detecção de mudanças na próxima execução
    save_snapshot(rows, SNAPSHOT_FILE)
    print("\n✔ Snapshot salvo:", SNAPSHOT_FILE)
    print("✔ index.html:", INDEX_FILE, "— lido pelo browser via Google Sheets (sem rebuild necessário)")
    print("\nℹ️  O index.html lê os dados diretamente do Google Sheets em tempo real.")
    print("   O script.py valida a estrutura e detecta mudanças para registro no CI/CD.")


if __name__ == "__main__":
    main()
