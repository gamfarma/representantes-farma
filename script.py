#!/usr/bin/env python3
"""
script.py — GAM Farma | Rede de Representantes
Lê a planilha do Google Sheets (CSV público) e gera o index.html atualizado.
Detecta automaticamente qualquer alteração na planilha:
  - novas colunas / linhas
  - mudança de nome, função, telefone, e-mail
  - representantes comerciais + razão social
  - coordenadores de equipe, gerentes de contas, coordenadores de médias redes
  - dedicados, projetos especiais, televendas, expansão

Uso:
  python script.py
  (executado pelo GitHub Actions via deploy.yml)
"""

import csv
import io
import os
import re
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime

# ─────────────────────────────────────────────
# CONFIG — altere apenas estas constantes
# ─────────────────────────────────────────────
CSV_URL = (
    "https://docs.google.com/spreadsheets/d/e/"
    "2PACX-1vQJRPejEYUGjqFiruPTGJuS2Itk6qjvyk6moB4_ChCe5_z4_CW0jYcYXJFimYYw4kGcbP2fpdRccLkq"
    "/pub?output=csv"
)
OUTPUT_FILE = "index.html"      # nome fixo — não altere
SCRIPT_FILE = "script.py"       # nome fixo — não altere
DEPLOY_FILE = "deploy.yml"      # nome fixo — não altere
LOGO_URL = (
    "https://raw.githubusercontent.com/gamfarma/imagem-site/"
    "2091104c3fa6efcc97594176ed36b38218ffa0f2/Logo%20GAM%20Nova%20Branca.png"
)
REFRESH_INTERVAL_MS = 5 * 60 * 1000  # 5 minutos em ms (usado no HTML)

# ─────────────────────────────────────────────
# NORMALIZAÇÃO DE CABEÇALHOS
# ─────────────────────────────────────────────
_HEADER_ALIASES = {
    "NOME REPRESENTANTE": "NOME",
    "RAZAO SOCIAL": "RAZAO_SOCIAL",
    "RAZÃO SOCIAL": "RAZAO_SOCIAL",
    "CONTATO COORPORATIVO": "TELEFONE",
    "CONTATO CORPORATIVO": "TELEFONE",
    "PRINCIPAIS CIDADES": "CIDADES",
    "COODENADOR": "COORD_COL",
    "COORDENADOR": "COORD_COL",
    "FUNCAO": "FUNCAO",
    "FUNÇÃO": "FUNCAO",
    "REGIAO": "REGIAO",
    "REGIÃO": "REGIAO",
}

def _norm(s: str) -> str:
    """Remove acentos e normaliza string para comparação."""
    import unicodedata
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return s.upper().strip()

def normalize_header(raw: str) -> str:
    key = _norm(raw)
    return _HEADER_ALIASES.get(key, key)

# ─────────────────────────────────────────────
# DOWNLOAD CSV
# ─────────────────────────────────────────────
def fetch_csv(url: str, retries: int = 3) -> list[dict]:
    cb = int(time.time() * 1000)
    full_url = f"{url}&cb={cb}"
    for attempt in range(retries):
        try:
            req = urllib.request.Request(
                full_url,
                headers={
                    "Cache-Control": "no-store",
                    "Pragma": "no-cache",
                    "User-Agent": "GAMFarma-Script/1.0",
                },
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
            break
        except urllib.error.URLError as e:
            if attempt == retries - 1:
                raise RuntimeError(f"Falha ao baixar CSV após {retries} tentativas: {e}") from e
            print(f"  Tentativa {attempt + 1} falhou, aguardando 5s…")
            time.sleep(5)

    lines = raw.splitlines()
    # Encontra linha de cabeçalho (contém DISTRITO e NOME/REPRESENTANTE)
    header_idx = -1
    update_date = ""
    for i, line in enumerate(lines):
        up = line.upper()
        if "DISTRITO" in up and ("NOME" in up or "REPRESENTANTE" in up):
            header_idx = i
            break
        m = re.search(r"\d{2}/\d{2}/\d{4}", line)
        if m:
            update_date = m.group()

    if header_idx == -1:
        raise RuntimeError("Cabeçalho não encontrado no CSV.")

    reader = csv.DictReader(
        io.StringIO("\n".join(lines[header_idx:])),
        skipinitialspace=True,
    )
    # Normaliza chaves
    rows = []
    for raw_row in reader:
        row = {normalize_header(k): (v or "").strip() for k, v in raw_row.items()}
        if not row.get("NOME"):
            continue
        row["_UPDATE_DATE"] = update_date
        rows.append(row)

    print(f"  {len(rows)} linhas carregadas (data: {update_date or 'N/A'})")
    return rows

# ─────────────────────────────────────────────
# HELPERS DE CAMPO
# ─────────────────────────────────────────────
def get_uf(row: dict) -> str:
    return row.get("UF", "").strip()

def get_funcao(row: dict) -> str:
    return row.get("FUNCAO", "").strip()

def get_regiao(row: dict) -> str:
    return row.get("REGIAO", "").strip()

def get_telefone(row: dict) -> str:
    return row.get("TELEFONE", "").strip()

def get_email(row: dict) -> str:
    return row.get("EMAIL", "").strip()

def get_cidades(row: dict) -> str:
    return row.get("CIDADES", "").strip()

def get_nome(row: dict) -> str:
    return row.get("NOME", "").strip()

def get_razao(row: dict) -> str:
    r = row.get("RAZAO_SOCIAL", "").strip()
    return "" if r == "-" else r

def get_distrito(row: dict) -> str:
    return row.get("DISTRITO", "").strip()

def is_coord_equipe(row: dict) -> bool:
    f = _norm(get_funcao(row))
    return "COORDENADOR EQUIPE" in f or "COORDENADOR DE EQUIPE" in f

def is_gerente_projetos(row: dict) -> bool:
    return "PROJETOS ESPECIAIS" in _norm(get_funcao(row))

def is_dedicado(row: dict) -> bool:
    return "DEDICADO" in _norm(get_funcao(row))

def is_gerente_contas(row: dict) -> bool:
    return "GERENTE DE CONTAS" in _norm(get_funcao(row))

def is_coord_contas(row: dict) -> bool:
    f = _norm(get_funcao(row))
    return "COORDENADOR DE CONTAS" in f or "MEDIAS REDES" in f

def is_client_role(row: dict) -> bool:
    return is_gerente_contas(row) or is_coord_contas(row)

def is_rep_comercial(row: dict) -> bool:
    return "REPRESENTANTE COMERCIAL" in _norm(get_funcao(row))

def get_ufs(uf_str: str) -> list[str]:
    if not uf_str or uf_str == "-" or "EXPANS" in uf_str.upper():
        return []
    parts = re.split(r"[/\-,\s]+", uf_str)
    return [p.strip().upper() for p in parts if re.match(r"^[A-Z]{2}$", p.strip().upper())]

# ─────────────────────────────────────────────
# PROCESSAMENTO DE GRUPOS
# ─────────────────────────────────────────────
def process_data(rows: list[dict]) -> dict:
    groups = []
    state_map: dict[str, list] = {}
    division_map: dict[str, list] = {}

    # 1) Coordenadores de Equipe por distrito
    coords_by_dist: dict[str, dict] = {}
    for r in rows:
        if is_coord_equipe(r):
            coords_by_dist[get_distrito(r)] = r

    assigned = set()
    group_members: dict[str, list] = {d: [] for d in coords_by_dist}

    # Passa 1: atribuição por base de distrito
    for dist, leader in coords_by_dist.items():
        assigned.add(id(leader))
        dist_bases = []
        for part in dist.split("/"):
            try:
                n = int(part.strip())
                dist_bases.append((n // 100) * 100)
            except ValueError:
                pass
        for r in rows:
            if id(r) in assigned:
                continue
            if any(fn(r) for fn in [is_coord_equipe, is_gerente_projetos, is_dedicado,
                                      is_gerente_contas, is_coord_contas]):
                continue
            d = get_distrito(r)
            if d in ("-", ""):
                continue
            try:
                n = int(d)
                if (n // 100) * 100 in dist_bases:
                    group_members[dist].append(r)
                    assigned.add(id(r))
            except ValueError:
                pass

    # Passa 2: fallback pela coluna COORDENADOR
    for dist, leader in coords_by_dist.items():
        leader_name_up = _norm(get_nome(leader))
        leader_first = leader_name_up.split()[0] if leader_name_up else ""
        for r in rows:
            if id(r) in assigned:
                continue
            if any(fn(r) for fn in [is_coord_equipe, is_gerente_projetos, is_dedicado,
                                      is_gerente_contas, is_coord_contas]):
                continue
            coord_col = _norm(r.get("COORD_COL", ""))
            if coord_col and (coord_col == leader_name_up or coord_col == leader_first):
                group_members[dist].append(r)
                assigned.add(id(r))

    # Monta objetos de grupo para coordenadores de equipe
    for dist, leader in coords_by_dist.items():
        members = group_members[dist]
        leader_uf = get_uf(leader)
        leader_region = get_regiao(leader)

        all_ufs: set[str] = set()
        for u in get_ufs(leader_uf):
            all_ufs.add(u)
        for m in members:
            for u in get_ufs(get_uf(m)):
                all_ufs.add(u)

        division = None
        if leader_uf == "-" or "TLV" in leader_region.upper():
            division = "Televendas"
        elif "EXPANS" in leader_uf.upper() or "EXPANS" in leader_region.upper():
            division = "EXPANSAO"
            for u in ["MS", "SP", "GO", "DF", "MT"]:
                all_ufs.add(u)

        groups.append({
            "leader": leader,
            "members": members,
            "dist_key": dist,
            "states": list(all_ufs),
            "division": division,
            "type": "coordEquipe",
        })

    # 2) Projetos Especiais + Dedicados
    gpe_row = next((r for r in rows if is_gerente_projetos(r)), None)
    if gpe_row:
        assigned.add(id(gpe_row))
        dedicados = [r for r in rows if is_dedicado(r)]
        for d in dedicados:
            assigned.add(id(d))
        all_ufs: set[str] = set()
        for u in get_ufs(get_uf(gpe_row)):
            all_ufs.add(u)
        for m in dedicados:
            for u in get_ufs(get_uf(m)):
                all_ufs.add(u)
        groups.append({
            "leader": gpe_row,
            "members": dedicados,
            "dist_key": "PROJ_ESP",
            "states": list(all_ufs),
            "division": "PROJ_ESP",
            "type": "projetosEspeciais",
        })

    # 3) Gerentes de Contas (individuais)
    for r in rows:
        if is_gerente_contas(r):
            assigned.add(id(r))
            ufs = get_ufs(get_uf(r))
            groups.append({
                "leader": r, "members": [], "dist_key": get_distrito(r),
                "states": ufs, "division": None, "type": "gerenteContas",
            })

    # 4) Coordenadores de Contas Médias Redes (individuais)
    for r in rows:
        if is_coord_contas(r):
            assigned.add(id(r))
            ufs = get_ufs(get_uf(r))
            groups.append({
                "leader": r, "members": [], "dist_key": get_distrito(r),
                "states": ufs, "division": None, "type": "coordContas",
            })

    # Monta stateMap e divisionMap
    for group in groups:
        if group["division"]:
            div = group["division"]
            division_map.setdefault(div, []).append(group)
            for uf in group["states"]:
                if uf and uf != "-":
                    state_map.setdefault(uf, []).append(group)
        else:
            for uf in group["states"]:
                if group["states"] and len(group["states"]) > 1 and group["members"]:
                    has_members = any(get_uf(m) == uf for m in group["members"])
                    if not has_members:
                        continue
                state_map.setdefault(uf, []).append(group)

    return {"groups": groups, "state_map": state_map, "division_map": division_map}

# ─────────────────────────────────────────────
# GERAÇÃO DO HTML
# ─────────────────────────────────────────────
HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta http-equiv="Cache-Control" content="no-store, no-cache, must-revalidate">
<meta http-equiv="Pragma" content="no-cache">
<meta http-equiv="Expires" content="0">
<title>GAM Farma — Rede de Representantes</title>
<style>
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0;}}
:root{{
  --primary:#0a2d6e;--primary-light:#1a4a9e;--accent:#FFB800;--purple:#8B5CF6;
  --bg:#f0f4f8;--surface:#fff;--border:#dde3ee;--text:#1a2340;--text-muted:#5a6a8a;
  --radius:12px;--shadow:0 2px 12px rgba(10,45,110,.10);--shadow-hover:0 6px 24px rgba(10,45,110,.18);
}}
html{{scroll-behavior:smooth;}}
body{{font-family:'Segoe UI',system-ui,-apple-system,sans-serif;background:var(--bg);color:var(--text);min-height:100vh;}}
#app-header{{background:linear-gradient(135deg,#0a2d6e 0%,#1a4a9e 60%,#0d3b8e 100%);color:#fff;position:sticky;top:0;z-index:100;box-shadow:0 2px 16px rgba(10,45,110,.25);}}
.header-inner{{max-width:1400px;margin:0 auto;padding:10px 20px;display:flex;align-items:center;gap:16px;flex-wrap:wrap;}}
.logo-img{{height:54px;width:auto;flex-shrink:0;filter:drop-shadow(0 2px 6px rgba(0,0,0,.18));}}
.header-titles{{flex:1;min-width:160px;}}
.header-titles h1{{font-size:16px;font-weight:700;letter-spacing:.5px;}}
.header-titles p{{font-size:11px;opacity:.8;margin-top:2px;}}
.header-search{{flex:2;min-width:200px;max-width:380px;position:relative;}}
.header-search input{{width:100%;padding:9px 16px 9px 38px;border-radius:24px;border:none;background:rgba(255,255,255,.18);color:#fff;font-size:14px;outline:none;transition:background .2s;}}
.header-search input::placeholder{{color:rgba(255,255,255,.7);}}
.header-search input:focus{{background:rgba(255,255,255,.28);}}
.search-icon{{position:absolute;left:12px;top:50%;transform:translateY(-50%);opacity:.7;font-size:15px;pointer-events:none;}}
.header-actions{{display:flex;align-items:center;gap:10px;flex-shrink:0;}}
.btn-refresh{{background:rgba(255,255,255,.18);border:1px solid rgba(255,255,255,.3);color:#fff;border-radius:8px;padding:8px 14px;cursor:pointer;font-size:13px;font-weight:600;transition:background .2s;display:flex;align-items:center;gap:6px;}}
.btn-refresh:hover{{background:rgba(255,255,255,.28);}}
.spinner{{display:inline-block;width:14px;height:14px;border:2px solid rgba(255,255,255,.4);border-top-color:#fff;border-radius:50%;animation:spin .7s linear infinite;}}
@keyframes spin{{to{{transform:rotate(360deg);}}}}
.timestamp{{font-size:11px;opacity:.75;white-space:nowrap;}}
#filter-bar{{background:var(--surface);border-bottom:1px solid var(--border);padding:10px 20px;}}
.filter-inner{{max-width:1400px;margin:0 auto;display:flex;align-items:center;gap:10px;flex-wrap:wrap;}}
.filter-label{{font-size:13px;font-weight:700;color:var(--text-muted);}}
.filter-select{{padding:7px 12px;border:1px solid var(--border);border-radius:8px;font-size:13px;background:var(--surface);color:var(--text);cursor:pointer;min-width:130px;}}
.btn-clear{{background:#fee;color:#c62828;border:1px solid #fcc;border-radius:8px;padding:7px 14px;font-size:12px;font-weight:700;cursor:pointer;transition:background .2s;}}
.btn-clear:hover{{background:#fdd;}}
#breadcrumb{{max-width:1400px;margin:0 auto;padding:12px 20px 0;font-size:13px;display:flex;align-items:center;gap:6px;flex-wrap:wrap;}}
.bc-item{{color:var(--primary);cursor:pointer;font-weight:600;}}
.bc-item:hover{{text-decoration:underline;}}
.bc-sep{{color:#bbb;}}
.bc-current{{color:var(--text-muted);font-weight:500;}}
#main-content{{max-width:1400px;margin:0 auto;padding:16px 20px 60px;}}
.section-title{{font-size:1.15rem;font-weight:800;margin-bottom:6px;display:flex;align-items:center;gap:10px;}}
.section-sub{{font-size:13px;color:var(--text-muted);margin-bottom:18px;}}
.count-badge{{background:var(--primary);color:#fff;font-size:11px;padding:3px 10px;border-radius:20px;font-weight:700;}}
#states-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:14px;}}
.state-card{{background:var(--surface);border-radius:var(--radius);padding:20px 16px;text-align:center;cursor:pointer;transition:transform .18s,box-shadow .18s;box-shadow:var(--shadow);border-top:4px solid var(--state-color);position:relative;overflow:hidden;}}
.state-card:hover{{transform:translateY(-4px);box-shadow:var(--shadow-hover);}}
.state-card::after{{content:'';position:absolute;right:-20px;top:-20px;width:80px;height:80px;background:var(--state-color);opacity:.06;border-radius:50%;}}
.state-sigla{{font-size:28px;font-weight:900;color:var(--state-color);line-height:1;}}
.state-name{{font-size:12px;color:var(--text-muted);margin-top:4px;font-weight:600;}}
.state-count{{font-size:11px;color:var(--text-muted);margin-top:6px;opacity:.7;}}
.state-card.division-card{{border-top:4px solid var(--purple);background:linear-gradient(135deg,#faf5ff 0%,#fff 100%);}}
.state-card.division-card .state-sigla{{color:var(--purple);font-size:20px;}}
#coordinators-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:16px;}}
.coord-card{{background:var(--surface);border-radius:var(--radius);box-shadow:var(--shadow);overflow:hidden;transition:box-shadow .2s;}}
.coord-card:hover{{box-shadow:var(--shadow-hover);}}
.coord-header{{padding:16px;color:#fff;position:relative;overflow:hidden;}}
.coord-header::after{{content:'';position:absolute;right:-20px;top:-20px;width:100px;height:100px;background:rgba(255,255,255,.08);border-radius:50%;}}
.coord-region-highlight{{font-size:16px;font-weight:900;margin-bottom:4px;text-shadow:0 1px 3px rgba(0,0,0,.15);letter-spacing:.3px;}}
.coord-func{{font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:1.2px;opacity:.85;margin-bottom:2px;}}
.coord-name{{font-size:15px;font-weight:700;line-height:1.3;}}
.coord-body{{padding:12px 16px;display:flex;flex-direction:column;gap:6px;}}
.coord-contact{{display:flex;align-items:center;gap:8px;font-size:13px;}}
.coord-contact a{{color:var(--primary);text-decoration:none;font-weight:500;transition:opacity .2s;}}
.coord-contact a:hover{{opacity:.7;text-decoration:underline;}}
.contact-icon{{font-size:15px;flex-shrink:0;}}
.coord-footer{{padding:10px 16px;border-top:1px solid var(--border);display:flex;align-items:center;justify-content:space-between;}}
.members-count{{font-size:12px;color:var(--text-muted);}}
.btn-team{{background:var(--primary);color:#fff;border:none;border-radius:8px;padding:7px 14px;font-size:12px;font-weight:700;cursor:pointer;transition:background .2s;}}
.btn-team:hover{{background:var(--primary-light);}}
.team-leader-header{{border-radius:var(--radius);padding:20px 24px;color:#fff;margin-bottom:20px;display:flex;flex-wrap:wrap;align-items:flex-start;gap:16px;box-shadow:var(--shadow-hover);position:relative;overflow:hidden;}}
.team-leader-header::after{{content:'';position:absolute;right:-30px;top:-30px;width:140px;height:140px;background:rgba(255,255,255,.07);border-radius:50%;}}
.tlh-avatar{{width:56px;height:56px;background:rgba(255,255,255,.22);border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:24px;font-weight:900;flex-shrink:0;border:2px solid rgba(255,255,255,.4);}}
.tlh-info-block{{flex:1;min-width:200px;}}
.tlh-region-highlight{{font-size:18px;font-weight:900;margin-bottom:2px;text-shadow:0 1px 3px rgba(0,0,0,.15);}}
.tlh-func{{font-size:10px;font-weight:700;letter-spacing:1.5px;text-transform:uppercase;opacity:.8;margin-bottom:4px;}}
.tlh-name{{font-size:22px;font-weight:900;line-height:1.2;margin-bottom:4px;}}
.tlh-region{{font-size:13px;opacity:.9;margin-bottom:10px;}}
.tlh-contacts{{display:flex;flex-wrap:wrap;gap:12px;}}
.tlh-contact-item{{display:flex;align-items:center;gap:6px;font-size:13px;}}
.tlh-contact-item a{{color:rgba(255,255,255,.92);text-decoration:none;font-weight:600;transition:opacity .2s;}}
.tlh-contact-item a:hover{{opacity:.75;text-decoration:underline;}}
.table-wrapper{{overflow-x:auto;border-radius:var(--radius);box-shadow:var(--shadow);}}
table{{width:100%;border-collapse:collapse;background:var(--surface);font-size:13px;}}
thead tr{{background:var(--primary);color:#fff;}}
th{{padding:12px 14px;text-align:left;font-weight:700;font-size:12px;letter-spacing:.5px;white-space:nowrap;}}
td{{padding:11px 14px;border-bottom:1px solid var(--border);vertical-align:middle;}}
tbody tr:last-child td{{border-bottom:none;}}
tbody tr:hover{{background:#f5f8ff;}}
.func-badge{{display:inline-block;padding:3px 10px;border-radius:20px;font-size:11px;font-weight:700;white-space:nowrap;}}
.badge-rep{{background:#e8f5e9;color:#1b5e20;}}
.badge-cv{{background:#e3f2fd;color:#0d47a1;}}
.badge-tlv{{background:#e3f2fd;color:#0d47a1;}}
.badge-ger{{background:#fce4ec;color:#880e4f;}}
.badge-coord-med{{background:#fff3e0;color:#bf360c;}}
.badge-ded{{background:#f3e5f5;color:#4a148c;}}
.badge-coord{{background:#e8eaf6;color:#1a237e;}}
.badge-default{{background:#eceff1;color:#37474f;}}
.btn-cities{{background:#e8f0fe;color:var(--primary);border:none;border-radius:8px;padding:5px 10px;font-size:12px;font-weight:600;cursor:pointer;transition:background .2s;white-space:nowrap;}}
.btn-cities:hover{{background:#c5d8fc;}}
.contact-link{{color:var(--primary);text-decoration:none;font-weight:500;}}
.contact-link:hover{{text-decoration:underline;}}
.btn-back{{display:inline-flex;align-items:center;gap:6px;background:var(--surface);border:1px solid var(--border);color:var(--primary);border-radius:8px;padding:8px 16px;font-size:13px;font-weight:700;cursor:pointer;margin-bottom:16px;transition:background .2s,box-shadow .2s;box-shadow:var(--shadow);}}
.btn-back:hover{{background:#e8f0fe;box-shadow:var(--shadow-hover);}}
#modal-overlay{{display:none;position:fixed;inset:0;background:rgba(10,20,50,.55);z-index:1000;align-items:center;justify-content:center;padding:20px;}}
#modal-overlay.open{{display:flex;}}
.modal-box{{background:var(--surface);border-radius:14px;padding:28px;max-width:520px;width:100%;max-height:80vh;overflow-y:auto;position:relative;box-shadow:0 12px 48px rgba(10,45,110,.25);animation:modalIn .22s ease;}}
@keyframes modalIn{{from{{transform:scale(.92);opacity:0;}}to{{transform:scale(1);opacity:1;}}}}
.modal-close{{position:absolute;top:14px;right:16px;background:none;border:none;font-size:22px;cursor:pointer;color:var(--text-muted);line-height:1;transition:color .2s;}}
.modal-close:hover{{color:#c62828;}}
.modal-title{{font-size:18px;font-weight:800;color:var(--primary);margin-bottom:4px;padding-right:30px;}}
.modal-subtitle{{font-size:13px;color:var(--text-muted);margin-bottom:18px;}}
.cities-container{{display:flex;flex-wrap:wrap;gap:8px;}}
.city-tag{{background:#e8f0fe;color:var(--primary);border-radius:20px;padding:5px 14px;font-size:13px;font-weight:600;}}
#progress-bar{{position:fixed;bottom:0;left:0;height:3px;background:#4caf50;z-index:9999;transition:width 1s linear;width:100%;}}
.empty-state{{text-align:center;padding:60px 20px;color:var(--text-muted);}}
.empty-icon{{font-size:48px;margin-bottom:12px;}}
.empty-text{{font-size:16px;font-weight:600;}}
#loading-state{{display:flex;flex-direction:column;align-items:center;justify-content:center;padding:80px 20px;gap:14px;}}
#loading-state .spinner{{width:36px;height:36px;border-width:3px;border-color:#ccc;border-top-color:var(--primary);}}
#error-state{{display:none;text-align:center;padding:60px 20px;}}
.district-label{{font-size:10px;background:rgba(255,255,255,.22);border-radius:6px;padding:2px 7px;display:inline-block;margin-top:4px;font-weight:600;letter-spacing:.5px;}}
.no-data{{color:#bbb;font-style:italic;font-size:12px;}}
.razao-social{{font-size:.78em;color:#5a6a8a;font-style:italic;margin-top:2px;}}
@media(max-width:600px){{
  .header-inner{{padding:10px 14px;gap:10px;}}
  .header-search{{min-width:100%;order:3;}}
  .logo-img{{height:40px;}}
  #main-content{{padding:14px;}}
  #states-grid{{grid-template-columns:repeat(auto-fill,minmax(120px,1fr));gap:10px;}}
  #coordinators-grid{{grid-template-columns:1fr;}}
  th,td{{padding:9px 10px;}}
  .team-leader-header{{padding:16px;}}
  .tlh-name{{font-size:18px;}}
}}
</style>
</head>
<body>
<header id="app-header">
  <div class="header-inner">
    <img src="{logo_url}" class="logo-img" alt="GAM Farma Logo" onerror="this.style.display='none'">
    <div class="header-titles">
      <h1>Rede de Representantes</h1>
      <p>Diretório comercial interativo</p>
    </div>
    <div class="header-search">
      <span class="search-icon">&#128269;</span>
      <input type="text" id="search-input" placeholder="Buscar por nome, cidade, região…" autocomplete="off">
    </div>
    <div class="header-actions">
      <button class="btn-refresh" id="btn-refresh">
        <span id="refresh-icon">&#128260;</span>
        Atualizar
      </button>
      <span class="timestamp" id="timestamp"></span>
    </div>
  </div>
</header>
<div id="filter-bar">
  <div class="filter-inner">
    <span class="filter-label">Filtrar:</span>
    <select class="filter-select" id="filter-uf"><option value="">Todos os estados</option></select>
    <select class="filter-select" id="filter-func">
      <option value="">Todas as funções</option>
      <option value="coordenador de equipe">Coordenadores de Equipe</option>
      <option value="representante comercial">Representante Comercial</option>
      <option value="consultor de vendas">Consultor de Vendas</option>
      <option value="televendas">Televendas</option>
      <option value="gerente de contas">Gerente de Contas</option>
      <option value="médias redes">Coordenador de Médias Redes</option>
      <option value="dedicados">Dedicados</option>
      <option value="projetos especiais">Gerente de Projetos Especiais</option>
    </select>
    <select class="filter-select" id="filter-region"><option value="">Todas as regiões</option></select>
    <button class="btn-clear" id="btn-clear">&#10005; Limpar</button>
  </div>
</div>
<div id="breadcrumb"></div>
<div id="main-content">
  <div id="loading-state">
    <span class="spinner"></span>
    <span style="color:var(--text-muted);font-size:14px">Carregando dados da planilha…</span>
  </div>
  <div id="error-state">
    <div class="empty-icon">&#9888;&#65039;</div>
    <div class="empty-text" id="error-msg">Erro ao carregar dados</div>
    <button class="btn-team" id="btn-retry" style="margin-top:16px">Tentar novamente</button>
  </div>
  <div id="view-states" style="display:none"></div>
  <div id="view-coordinators" style="display:none"></div>
  <div id="view-team" style="display:none"></div>
  <div id="view-search" style="display:none"></div>
</div>
<div id="modal-overlay">
  <div class="modal-box">
    <button class="modal-close" id="modal-close">&#10005;</button>
    <div class="modal-title" id="modal-title"></div>
    <div class="modal-subtitle" id="modal-subtitle"></div>
    <div class="cities-container" id="modal-cities"></div>
  </div>
</div>
<div id="progress-bar"></div>
<script>
const CSV_URL='{csv_url}';
const REFRESH_INTERVAL={refresh_interval};
const STATE_COLORS={{SC:'#1565c0',RS:'#c62828',PR:'#2e7d32',MS:'#e65100',SP:'#6a1b9a',GO:'#00838f',DF:'#4527a0',MT:'#827717',MG:'#4e342e',RJ:'#00695c',BA:'#f57f17',DEFAULT:'#607d8b'}};
const DIVISION_COLORS={{'Televendas':'#1565c0','EXPANSAO':'#00838f','PROJ_ESP':'#2e7d32'}};
const STATE_NAMES={{AC:'Acre',AL:'Alagoas',AP:'Amapá',AM:'Amazonas',BA:'Bahia',CE:'Ceará',DF:'Distrito Federal',ES:'Espírito Santo',GO:'Goiás',MA:'Maranhão',MT:'Mato Grosso',MS:'Mato Grosso do Sul',MG:'Minas Gerais',PA:'Pará',PB:'Paraíba',PR:'Paraná',PE:'Pernambuco',PI:'Piauí',RJ:'Rio de Janeiro',RN:'Rio Grande do Norte',RS:'Rio Grande do Sul',RO:'Rondônia',RR:'Roraima',SC:'Santa Catarina',SP:'São Paulo',SE:'Sergipe',TO:'Tocantins'}};
let appData={{rows:[],groups:[],stateMap:{{}},divisionMap:{{}},updateDate:''}};
let currentView='states',currentState=null,currentGroup=null;
let refreshTimer=null,progressTimer=null,progressStart=null;

function parseCSV(text){{
  const lines=text.split(/\r?\n/);
  let headerIdx=-1,updateDate='';
  for(let i=0;i<lines.length;i++){{
    const up=lines[i].toUpperCase();
    if(up.includes('DISTRITO')&&(up.includes('NOME')||up.includes('REPRESENTANTE'))){{headerIdx=i;break;}}
    const dm=lines[i].match(/\d{{2}}\/\d{{2}}\/\d{{4}}/);
    if(dm)updateDate=dm[0];
  }}
  if(headerIdx===-1)return{{rows:[],updateDate}};
  const rawH=parseLine(lines[headerIdx]);
  const headers=rawH.map(h=>normalizeHeader(h));
  const rows=[];
  for(let i=headerIdx+1;i<lines.length;i++){{
    const line=lines[i].trim();if(!line)continue;
    const cells=parseLine(lines[i]);
    const row={{}};
    headers.forEach((h,idx)=>{{row[h]=(cells[idx]||'').trim();}});
    if(!row['NOME']||row['NOME']==='')continue;
    rows.push(row);
  }}
  return{{rows,updateDate}};
}}
function parseLine(line){{
  const r=[];let cur='',inQ=false;
  for(let i=0;i<line.length;i++){{
    const ch=line[i];
    if(ch==='"'){{if(inQ&&line[i+1]==='"'){{cur+='"';i++;}}else inQ=!inQ;}}
    else if(ch===','&&!inQ){{r.push(cur);cur='';}}
    else cur+=ch;
  }}
  r.push(cur);return r;
}}
function normalizeHeader(h){{
  let s=h.normalize('NFD').replace(/[\u0300-\u036f]/g,'').toUpperCase().trim();
  s=s.replace('COORPORATIVO','CORPORATIVO').replace('COODENADOR','COORDENADOR');
  if(s==='NOME REPRESENTANTE')s='NOME';
  if(s==='RAZAO SOCIAL'||s==='RAZÃO SOCIAL')s='RAZAO_SOCIAL';
  if(s==='CONTATO CORPORATIVO')s='TELEFONE';
  if(s==='PRINCIPAIS CIDADES')s='CIDADES';
  if(s==='FUNCAO'||s==='FUNÇÃO')s='FUNCAO';
  if(s==='REGIAO'||s==='REGIÃO')s='REGIAO';
  return s;
}}
function getFunc(r){{return r['FUNCAO']||'';}}
function getRegion(r){{return r['REGIAO']||r['REGIÃO']||'';}}
function getPhone(r){{return r['TELEFONE']||r['CONTATO CORPORATIVO']||r['CONTATO COORPORATIVO']||'';}}
function getEmail(r){{return r['EMAIL']||'';}}
function getCities(r){{return r['CIDADES']||r['PRINCIPAIS CIDADES']||'';}}
function getRazao(r){{const v=r['RAZAO_SOCIAL']||r['RAZÃO SOCIAL']||r['RAZAO SOCIAL']||'';return(v==='-')?'':v;}}
function getName(r){{return r['NOME']||'';}}
function getUF(r){{return(r['UF']||'').trim();}}
function getDistrito(r){{return(r['DISTRITO']||'').trim();}}
function isCoordEquipe(r){{const f=getFunc(r).toUpperCase();return f.includes('COORDENADOR EQUIPE')||f.includes('COORDENADOR DE EQUIPE');}}
function isGerenteProjetos(r){{return getFunc(r).toUpperCase().includes('PROJETOS ESPECIAIS');}}
function isDedicado(r){{return getFunc(r).toUpperCase().includes('DEDICADO');}}
function isGerenteContas(r){{return getFunc(r).toLowerCase().includes('gerente de contas');}}
function isCoordContas(r){{const f=getFunc(r).toLowerCase();return f.includes('coordenador de contas')||f.includes('medias redes')||f.includes('médias redes');}}
function isClientRole(r){{return isGerenteContas(r)||isCoordContas(r);}}
function isRepComercial(r){{return getFunc(r).toLowerCase().includes('representante comercial');}}
function getUFs(s){{
  if(!s||s==='-'||s.toUpperCase().includes('EXPANS'))return[];
  return s.split(/[\/\-,\s]+/).map(p=>p.trim().toUpperCase()).filter(p=>p.length===2&&/^[A-Z]{{2}}$/.test(p));
}}

function processData(rows){{
  const groups=[],stateMap={{}},divisionMap={{}};
  const coordsByDist={{}};
  rows.forEach(r=>{{if(isCoordEquipe(r))coordsByDist[getDistrito(r)]=r;}});
  const assignedSet=new Set(),groupMembers={{}};
  Object.keys(coordsByDist).forEach(dist=>{{
    const leader=coordsByDist[dist];assignedSet.add(leader);groupMembers[dist]=[];
    const bases=dist.split('/').map(p=>{{const n=parseInt(p);return isNaN(n)?null:Math.floor(n/100)*100;}}).filter(b=>b!==null);
    rows.forEach(r=>{{
      if(r===leader||assignedSet.has(r))return;
      if(isCoordEquipe(r)||isGerenteProjetos(r)||isDedicado(r)||isGerenteContas(r)||isCoordContas(r))return;
      const d=getDistrito(r);if(d==='-'||d==='')return;
      const n=parseInt(d);if(isNaN(n))return;
      if(bases.includes(Math.floor(n/100)*100)){{groupMembers[dist].push(r);assignedSet.add(r);}}
    }});
  }});
  Object.keys(coordsByDist).forEach(dist=>{{
    const leader=coordsByDist[dist];
    const nameUp=getName(leader).toUpperCase().trim();
    const first=nameUp.split(' ')[0];
    rows.forEach(r=>{{
      if(assignedSet.has(r))return;
      if(isCoordEquipe(r)||isGerenteProjetos(r)||isDedicado(r)||isGerenteContas(r)||isCoordContas(r))return;
      const cc=(r['COORDENADOR']||r['COODENADOR']||'').toUpperCase().trim();
      if(cc&&(cc===nameUp||cc===first)){{groupMembers[dist].push(r);assignedSet.add(r);}}
    }});
  }});
  Object.keys(coordsByDist).forEach(dist=>{{
    const leader=coordsByDist[dist];const members=groupMembers[dist];
    const luf=getUF(leader);const lreg=getRegion(leader);
    const allUFs=new Set();
    getUFs(luf).forEach(u=>allUFs.add(u));
    members.forEach(m=>getUFs(getUF(m)).forEach(u=>allUFs.add(u)));
    let division=null;
    if(luf==='-'||lreg.toUpperCase().includes('TLV'))division='Televendas';
    else if(luf.toUpperCase().includes('EXPANS')||lreg.toUpperCase().includes('EXPANS')){{
      division='EXPANSAO';['MS','SP','GO','DF','MT'].forEach(u=>allUFs.add(u));
    }}
    groups.push({{leader,members,distKey:dist,states:Array.from(allUFs),division,type:'coordEquipe'}});
  }});
  const gpe=rows.find(r=>isGerenteProjetos(r));
  if(gpe){{
    assignedSet.add(gpe);
    const deds=rows.filter(r=>isDedicado(r));deds.forEach(d=>assignedSet.add(d));
    const allUFs=new Set();getUFs(getUF(gpe)).forEach(u=>allUFs.add(u));
    deds.forEach(m=>getUFs(getUF(m)).forEach(u=>allUFs.add(u)));
    groups.push({{leader:gpe,members:deds,distKey:'PROJ_ESP',states:Array.from(allUFs),division:'PROJ_ESP',type:'projetosEspeciais'}});
  }}
  rows.filter(r=>isGerenteContas(r)).forEach(r=>{{
    assignedSet.add(r);const ufs=getUFs(getUF(r));
    groups.push({{leader:r,members:[],distKey:getDistrito(r),states:ufs,division:null,type:'gerenteContas'}});
  }});
  rows.filter(r=>isCoordContas(r)).forEach(r=>{{
    assignedSet.add(r);const ufs=getUFs(getUF(r));
    groups.push({{leader:r,members:[],distKey:getDistrito(r),states:ufs,division:null,type:'coordContas'}});
  }});
  groups.forEach(group=>{{
    if(group.division){{
      const div=group.division;
      if(!divisionMap[div])divisionMap[div]=[];divisionMap[div].push(group);
      group.states.forEach(uf=>{{if(uf&&uf!=='-'){{if(!stateMap[uf])stateMap[uf]=[];stateMap[uf].push(group);}}}});
    }}else{{
      group.states.forEach(uf=>{{
        if(group.states.length>1&&group.members.length>0){{
          if(!group.members.some(m=>getUF(m)===uf))return;
        }}
        if(!stateMap[uf])stateMap[uf]=[];stateMap[uf].push(group);
      }});
    }}
  }});
  return{{groups,stateMap,divisionMap}};
}}

async function fetchData(){{
  showLoading();
  try{{
    const url=`${{CSV_URL}}&cb=${{Date.now()}}_${{Math.random().toString(36).slice(2)}}`;
    const resp=await fetch(url,{{cache:'no-store',headers:{{'Cache-Control':'no-store','Pragma':'no-cache'}}}});
    if(!resp.ok)throw new Error(`HTTP ${{resp.status}}`);
    const text=await resp.text();
    const {{rows,updateDate}}=parseCSV(text);
    if(rows.length===0)throw new Error('Nenhum dado encontrado na planilha.');
    const {{groups,stateMap,divisionMap}}=processData(rows);
    appData={{rows,groups,stateMap,divisionMap,updateDate}};
    populateFilters();
    const now=new Date();
    document.getElementById('timestamp').textContent=`Atualizado: ${{now.getHours().toString().padStart(2,'0')}}:${{now.getMinutes().toString().padStart(2,'0')}}`;
    hideLoading();renderCurrentView();startProgressBar();scheduleRefresh();
  }}catch(e){{showError(e.message||'Erro ao carregar dados');}}
}}

function populateFilters(){{
  const ufSel=document.getElementById('filter-uf');
  const regSel=document.getElementById('filter-region');
  const allUFs=new Set();
  appData.rows.forEach(r=>getUFs(getUF(r)).forEach(u=>allUFs.add(u)));
  ufSel.innerHTML='<option value="">Todos os estados</option>';
  Array.from(allUFs).sort().forEach(uf=>{{
    const o=document.createElement('option');o.value=uf;
    o.textContent=`${{uf}} — ${{STATE_NAMES[uf]||uf}}`;ufSel.appendChild(o);
  }});
  const regs=new Set();
  appData.rows.forEach(r=>{{const reg=getRegion(r).trim();if(reg&&reg!=='-')regs.add(reg);}});
  regSel.innerHTML='<option value="">Todas as regiões</option>';
  Array.from(regs).sort().forEach(reg=>{{
    const o=document.createElement('option');o.value=reg.toLowerCase();o.textContent=reg;regSel.appendChild(o);
  }});
}}

function showLoading(){{document.getElementById('loading-state').style.display='flex';document.getElementById('error-state').style.display='none';hideAllViews();}}
function hideLoading(){{document.getElementById('loading-state').style.display='none';}}
function showError(msg){{document.getElementById('loading-state').style.display='none';document.getElementById('error-state').style.display='block';document.getElementById('error-msg').textContent=msg||'Erro desconhecido.';}}

function renderCurrentView(){{
  const query=document.getElementById('search-input').value.trim().toLowerCase();
  const fUF=document.getElementById('filter-uf').value;
  const fFunc=document.getElementById('filter-func').value.toLowerCase();
  const fReg=document.getElementById('filter-region').value.toLowerCase();
  const hasFilter=query||fFunc||fReg;
  if(hasFilter||(query&&fUF)){{renderSearchResults(query,fUF,fFunc,fReg);return;}}
  if(fUF&&!hasFilter){{navigateToState(fUF);return;}}
  if(currentView==='states')renderStates();
  else if(currentView==='coordinators')renderCoordinators(currentState);
  else if(currentView==='team')renderTeam(currentGroup,currentState);
}}

function renderStates(){{
  currentView='states';hideAllViews();updateBreadcrumb([{{label:'Início'}}]);
  const container=document.getElementById('view-states');container.style.display='block';
  const ufs=Object.keys(appData.stateMap).filter(uf=>appData.stateMap[uf].length>0).sort();
  let h=`<div class="section-title">&#128506;&#65039; Cobertura Comercial <span class="count-badge">${{ufs.length}}</span></div>
    <p class="section-sub">Selecione um estado para ver coordenadores e equipes.</p>
    <div id="states-grid">`;
  ufs.forEach(uf=>{{
    const groups=appData.stateMap[uf];
    const color=STATE_COLORS[uf]||STATE_COLORS.DEFAULT;
    const name=STATE_NAMES[uf]||uf;
    h+=`<div class="state-card" style="--state-color:${{color}}" onclick="navigateToState('${{uf}}')" title="${{name}}">
      <div class="state-sigla">${{uf}}</div>
      <div class="state-name">${{name}}</div>
      <div class="state-count">${{groups.length}} grupo${{groups.length!==1?'s':''}}</div>
    </div>`;
  }});
  h+='</div>';
  container.innerHTML=h;
}}

function navigateToState(uf){{currentView='coordinators';currentState=uf;document.getElementById('filter-uf').value=uf;renderCoordinators(uf);}}
function navigateToDivision(div){{currentView='coordinators';currentState=div;renderDivisionCoordinators(div);}}

function renderCoordinators(uf){{
  hideAllViews();updateBreadcrumb([{{label:'Início',action:'goHome'}},{{label:`${{uf}} — ${{STATE_NAMES[uf]||uf}}`}}]);
  const container=document.getElementById('view-coordinators');container.style.display='block';
  const groups=appData.stateMap[uf]||[];
  const color=STATE_COLORS[uf]||STATE_COLORS.DEFAULT;
  let h=`<button class="btn-back" onclick="goHome()">&#8592; Voltar</button>
    <div class="section-title" style="color:${{color}}">${{uf}} — ${{STATE_NAMES[uf]||uf}} <span class="count-badge" style="background:${{color}}">${{groups.length}}</span></div>
    <p class="section-sub">Coordenadores, gerentes e representantes com atuação neste estado.</p>
    <div id="coordinators-grid">`;
  if(!groups.length)h+=`<div class="empty-state"><div class="empty-icon">&#128269;</div><div class="empty-text">Nenhum grupo encontrado.</div></div>`;
  else groups.forEach(g=>{{h+=renderCoordCard(g,uf);}});
  h+='</div>';container.innerHTML=h;
}}

function renderDivisionCoordinators(div){{
  hideAllViews();updateBreadcrumb([{{label:'Início',action:'goHome'}},{{label:div}}]);
  const container=document.getElementById('view-coordinators');container.style.display='block';
  const groups=appData.divisionMap[div]||[];
  const color=DIVISION_COLORS[div]||'#8B5CF6';
  const divLabel=div==='PROJ_ESP'?'Projetos Especiais — SUL':div==='EXPANSAO'?'Expansão — Centro Oeste e Sudeste':div;
  let h=`<button class="btn-back" onclick="goHome()">&#8592; Voltar</button>
    <div class="section-title" style="color:${{color}}">${{divLabel}} <span class="count-badge" style="background:${{color}}">${{groups.length}}</span></div>
    <p class="section-sub">Equipes desta divisão.</p><div id="coordinators-grid">`;
  groups.forEach(g=>{{h+=renderCoordCard(g,null);}});
  h+='</div>';container.innerHTML=h;
}}

function renderCoordCard(group,uf){{
  const leader=group.leader;if(!leader)return'';
  const func=getFunc(leader);
  const phone=getPhone(leader);
  const email=getEmail(leader);
  let region=getRegion(leader);
  if(group.division==='EXPANSAO')region='Centro Oeste e Sudeste';
  const headerColor=group.division?(DIVISION_COLORS[group.division]||'#8B5CF6'):getHeaderColor(func,uf);
  const isClient=isClientRole(leader);
  const memberCount=(uf&&group.states&&group.states.length>1)?group.members.filter(m=>getUF(m)===uf).length:group.members.length;
  let h=`<div class="coord-card"><div class="coord-header" style="background:${{headerColor}}">`;
  if(region&&region!=='-')h+=`<div class="coord-region-highlight">&#128205; ${{region}}</div>`;
  if(group.division){{
    const dl=group.division==='PROJ_ESP'?'Projetos Especiais':group.division==='EXPANSAO'?'Expansão':group.division;
    h+=`<div style="display:inline-block;background:rgba(255,255,255,.25);color:#fff;font-size:11px;padding:2px 10px;border-radius:20px;margin-bottom:4px;font-weight:600;">${{dl}}</div>`;
  }}
  h+=`<div class="coord-func">${{func}}</div><div class="coord-name">${{getName(leader)}}</div>
    <span class="district-label">Distrito ${{group.distKey}}</span>
    </div><div class="coord-body">
    ${{phone?`<div class="coord-contact"><span class="contact-icon">&#128241;</span><a href="tel:${{phone.replace(/\D/g,'')}}">${{phone}}</a></div>`:`<div class="coord-contact"><span class="contact-icon">&#128241;</span><span class="no-data">Sem contato</span></div>`}}
    ${{email?`<div class="coord-contact"><span class="contact-icon">&#9993;&#65039;</span><a href="mailto:${{email}}">${{email}}</a></div>`:`<div class="coord-contact"><span class="contact-icon">&#9993;&#65039;</span><span class="no-data">Sem e-mail</span></div>`}}
    </div><div class="coord-footer">`;
  if(isClient){{
    h+=`<span class="members-count" style="color:var(--text-muted);font-style:italic;">Atua individualmente</span>`;
  }}else if(memberCount>0){{
    h+=`<span class="members-count">&#128101; ${{memberCount}} membro${{memberCount!==1?'s':''}}</span>
      <button class="btn-team" onclick="navigateToTeam('${{escapeAttr(group.distKey)}}','${{escapeAttr(uf||currentState||'')}}')">Ver equipe &#8594;</button>`;
  }}else{{
    h+=`<span class="members-count">&#128101; Equipe</span>
      <button class="btn-team" onclick="navigateToTeam('${{escapeAttr(group.distKey)}}','${{escapeAttr(uf||currentState||'')}}')">Ver equipe &#8594;</button>`;
  }}
  h+=`</div></div>`;
  return h;
}}

function getHeaderColor(func,uf){{
  const f=func.toLowerCase();
  if(f.includes('projetos especiais'))return'#2e7d32';
  if(f.includes('gerente de contas'))return'#ad1457';
  if(f.includes('medias redes')||f.includes('médias redes'))return'#e65100';
  if(uf&&STATE_COLORS[uf])return STATE_COLORS[uf];
  return STATE_COLORS.DEFAULT;
}}

function navigateToTeam(distKey,fromState){{
  const group=appData.groups.find(g=>g.distKey===distKey);if(!group)return;
  currentView='team';currentGroup=group;currentState=fromState;renderTeam(group,fromState);
}}

function renderTeam(group,fromState){{
  if(!group)return;hideAllViews();
  const leaderName=group.leader?getName(group.leader):'Equipe';
  const isDivision=!!group.division;
  const showStateBc=fromState&&STATE_NAMES[fromState];
  updateBreadcrumb([
    {{label:'Início',action:'goHome'}},
    showStateBc?{{label:`${{fromState}} — ${{STATE_NAMES[fromState]}}`,action:`navigateToState_bc_${{fromState}}`}}
      :(isDivision?{{label:group.division,action:`navigateToDivision_bc_${{group.division}}`}}
        :{{label:`${{fromState}} — ${{STATE_NAMES[fromState]||fromState||''}}`,action:`navigateToState_bc_${{fromState}}`}}),
    {{label:leaderName}}
  ]);
  const container=document.getElementById('view-team');container.style.display='block';
  const color=isDivision?(DIVISION_COLORS[group.division]||'#8B5CF6'):(STATE_COLORS[fromState]||STATE_COLORS.DEFAULT);
  const backAction=(fromState&&STATE_NAMES[fromState])?`navigateToState('${{escapeAttr(fromState)}}')`
    :(isDivision?`navigateToDivision('${{escapeAttr(group.division)}}')`:`navigateToState('${{escapeAttr(fromState||currentState||'')}}')`);
  let h=`<button class="btn-back" onclick="${{backAction}}">&#8592; Voltar</button>`;
  if(group.leader){{
    const ldr=group.leader;
    const lFunc=getFunc(ldr);const lPhone=getPhone(ldr);const lEmail=getEmail(ldr);
    let lRegion=getRegion(ldr);if(group.division==='EXPANSAO')lRegion='Centro Oeste e Sudeste';
    const initials=getName(ldr).split(' ').filter(w=>w.length>0).slice(0,2).map(w=>w[0]).join('').toUpperCase();
    h+=`<div class="team-leader-header" style="background:linear-gradient(135deg,${{color}} 0%,${{color}}cc 100%)">
      <div class="tlh-avatar">${{initials}}</div>
      <div class="tlh-info-block">
        ${{lRegion?`<div class="tlh-region-highlight">&#128205; ${{lRegion}}</div>`:''}}
        <div class="tlh-func">${{lFunc}}</div>
        <div class="tlh-name">${{getName(ldr)}}</div>
        <div class="tlh-contacts">
          ${{lPhone?`<div class="tlh-contact-item"><span>&#128241;</span><a href="tel:${{lPhone.replace(/\D/g,'')}}">${{lPhone}}</a></div>`:''}}
          ${{lEmail?`<div class="tlh-contact-item"><span>&#9993;&#65039;</span><a href="mailto:${{lEmail}}">${{lEmail}}</a></div>`:''}}
        </div>
      </div></div>`;
  }}
  let members=(fromState&&STATE_NAMES[fromState]&&group.states&&group.states.length>1)
    ?group.members.filter(m=>getUF(m)===fromState):group.members;
  const showFiltered=members.length!==group.members.length;
  h+=`<div class="section-title" style="color:${{color}}">&#128101; Equipe${{group.leader?' de '+getName(group.leader):''}}
    <span class="count-badge" style="background:${{color}}">${{members.length}} membro${{members.length!==1?'s':''}}</span></div>
    <p class="section-sub">${{group.distKey!=='PROJ_ESP'?'Distrito '+group.distKey:'Projetos Especiais — SUL'}}
    ${{showFiltered?' · Exibindo membros de '+fromState:(group.states.length>0?' · '+group.states.join(', '):'')}}</p>`;
  if(!members.length){{
    h+=`<div class="empty-state"><div class="empty-icon">&#128100;</div><div class="empty-text">Nenhum membro na equipe.</div></div>`;
  }}else{{
    h+=`<div class="table-wrapper"><table>
      <thead><tr><th>Nome</th><th>Função</th><th>Contato Corporativo</th><th>E-mail</th><th>UF</th><th>Região</th><th>Principais Cidades</th></tr></thead><tbody>`;
    members.forEach(m=>{{
      const func=getFunc(m);const badge=getFuncBadge(func);
      const phone=getPhone(m);const email=getEmail(m);
      const region=getRegion(m);const cities=getCities(m);
      const nome=getName(m);const uf=getUF(m);
      const razao=getRazao(m);const isRC=isRepComercial(m);const isClient=isClientRole(m);
      let citiesBtn='<span class="no-data">—</span>';
      if(cities&&!isClient){{
        citiesBtn=`<button class="btn-cities" onclick="openCitiesModal('${{escapeAttr(nome)}}','${{escapeAttr(region)}}','${{escapeAttr(cities)}}')">&#128205; Cidades</button>`;
      }}
      h+=`<tr>
        <td><div style="font-weight:700;margin-bottom:2px">${{nome}}</div>
          ${{isRC&&razao&&razao!=='-'&&razao!==''?`<div class="razao-social">&#127970; ${{razao}}</div>`:''}}
        </td>
        <td><span class="func-badge ${{badge.cls}}">${{badge.label}}</span></td>
        <td>${{phone?`<a class="contact-link" href="tel:${{phone.replace(/\D/g,'')}}">${{phone}}</a>`:'<span class="no-data">—</span>'}}</td>
        <td>${{email?`<a class="contact-link" href="mailto:${{email}}">${{email}}</a>`:'<span class="no-data">—</span>'}}</td>
        <td>${{uf||'—'}}</td>
        <td>${{region||'<span class="no-data">—</span>'}}</td>
        <td>${{citiesBtn}}</td>
      </tr>`;
    }});
    h+='</tbody></table></div>';
  }}
  container.innerHTML=h;
}}

function getFuncBadge(func){{
  const f=func.toLowerCase();
  if(f.includes('representante comercial'))return{{cls:'badge-rep',label:'Representante Comercial'}};
  if(f.includes('consultor de vendas'))return{{cls:'badge-cv',label:'Consultor de Vendas'}};
  if(f.includes('gerente de contas'))return{{cls:'badge-ger',label:'Gerente de Contas'}};
  if(f.includes('medias redes')||f.includes('médias redes'))return{{cls:'badge-coord-med',label:'Coordenador de Médias Redes'}};
  if(f.includes('dedicado'))return{{cls:'badge-ded',label:'Dedicado'}};
  if(f.includes('coordenador'))return{{cls:'badge-coord',label:'Coordenador'}};
  return{{cls:'badge-default',label:func||'—'}};
}}

function renderSearchResults(query,filterUF,filterFunc,filterRegion){{
  hideAllViews();
  updateBreadcrumb([{{label:'Início',action:'goHome'}},{{label:'Resultados da busca'}}]);
  const container=document.getElementById('view-search');container.style.display='block';
  let results=appData.rows.filter(r=>{{
    const nome=getName(r).toLowerCase();const uf=getUF(r).toUpperCase();
    const func=getFunc(r).toLowerCase();const region=getRegion(r).toLowerCase();
    const cities=getCities(r).toLowerCase();const razao=getRazao(r).toLowerCase();
    if(query&&!nome.includes(query)&&!cities.includes(query)&&!region.includes(query)&&!razao.includes(query))return false;
    if(filterUF){{const rowUFs=getUFs(uf);if(!rowUFs.includes(filterUF)&&!uf.includes(filterUF))return false;}}
    if(filterFunc&&!func.includes(filterFunc))return false;
    if(filterRegion&&!region.includes(filterRegion))return false;
    return true;
  }});
  let h=`<div class="section-title">&#128269; Resultados <span class="count-badge">${{results.length}}</span></div>
    <p class="section-sub">${{results.length}} resultado${{results.length!==1?'s':''}} encontrado${{results.length!==1?'s':''}}.</p>`;
  if(!results.length){{
    h+=`<div class="empty-state"><div class="empty-icon">&#128269;</div><div class="empty-text">Nenhum resultado encontrado.</div></div>`;
  }}else{{
    h+=`<div class="table-wrapper"><table>
      <thead><tr><th>Nome</th><th>Função</th><th>UF</th><th>Região</th><th>Contato</th><th>E-mail</th><th>Principais Cidades</th></tr></thead><tbody>`;
    results.forEach(r=>{{
      const func=getFunc(r);const badge=getFuncBadge(func);
      const phone=getPhone(r);const email=getEmail(r);
      const region=getRegion(r);const cities=getCities(r);
      const uf=getUF(r);const nome=getName(r);
      const razao=getRazao(r);const isRC=isRepComercial(r);const isClient=isClientRole(r);
      let citiesBtn='<span class="no-data">—</span>';
      if(cities&&!isClient){{
        citiesBtn=`<button class="btn-cities" onclick="openCitiesModal('${{escapeAttr(nome)}}','${{escapeAttr(region)}}','${{escapeAttr(cities)}}')">&#128205; Cidades</button>`;
      }}
      h+=`<tr>
        <td><strong>${{nome}}</strong>${{isRC&&razao&&razao!=='-'&&razao!==''?`<div class="razao-social">&#127970; ${{razao}}</div>`:''}} </td>
        <td><span class="func-badge ${{badge.cls}}">${{badge.label}}</span></td>
        <td>${{uf}}</td><td>${{region||'<span class="no-data">—</span>'}}</td>
        <td>${{phone?`<a class="contact-link" href="tel:${{phone.replace(/\D/g,'')}}">${{phone}}</a>`:'<span class="no-data">—</span>'}}</td>
        <td>${{email?`<a class="contact-link" href="mailto:${{email}}">${{email}}</a>`:'<span class="no-data">—</span>'}}</td>
        <td>${{citiesBtn}}</td>
      </tr>`;
    }});
    h+='</tbody></table></div>';
  }}
  container.innerHTML=h;
}}

function goHome(){{
  currentView='states';currentState=null;currentGroup=null;
  document.getElementById('filter-uf').value='';
  document.getElementById('filter-func').value='';
  document.getElementById('filter-region').value='';
  document.getElementById('search-input').value='';
  renderStates();
}}
function hideAllViews(){{['view-states','view-coordinators','view-team','view-search'].forEach(id=>document.getElementById(id).style.display='none');}}
function updateBreadcrumb(items){{
  const bc=document.getElementById('breadcrumb');
  if(items.length<=1&&items[0].label==='Início'){{bc.innerHTML='';return;}}
  let h='';
  items.forEach((item,i)=>{{
    if(i>0)h+='<span class="bc-sep">&#8250;</span>';
    if(i===items.length-1)h+=`<span class="bc-current">${{item.label}}</span>`;
    else if(item.action==='goHome')h+=`<span class="bc-item" onclick="goHome()">${{item.label}}</span>`;
    else if(item.action&&item.action.startsWith('navigateToState_bc_')){{
      const st=item.action.replace('navigateToState_bc_','');
      h+=`<span class="bc-item" onclick="navigateToState('${{escapeAttr(st)}}')">${{item.label}}</span>`;
    }}else if(item.action&&item.action.startsWith('navigateToDivision_bc_')){{
      const dv=item.action.replace('navigateToDivision_bc_','');
      h+=`<span class="bc-item" onclick="navigateToDivision('${{escapeAttr(dv)}}')">${{item.label}}</span>`;
    }}else h+=`<span class="bc-item" onclick="goHome()">${{item.label}}</span>`;
  }});
  bc.innerHTML=h;
}}

function openCitiesModal(nome,region,citiesStr){{
  document.getElementById('modal-title').textContent=nome;
  document.getElementById('modal-subtitle').textContent=`Principais cidades${{region?' — '+region:''}}`;
  const cities=citiesStr.split(/[,;]+/).map(c=>c.trim()).filter(c=>c&&c!=='-');
  document.getElementById('modal-cities').innerHTML=cities.length>0
    ?cities.map(c=>`<span class="city-tag">${{c}}</span>`).join('')
    :'<span class="no-data">Nenhuma cidade cadastrada.</span>';
  document.getElementById('modal-overlay').classList.add('open');
}}
function closeModal(){{document.getElementById('modal-overlay').classList.remove('open');}}
document.getElementById('modal-close').addEventListener('click',closeModal);
document.getElementById('modal-overlay').addEventListener('click',e=>{{if(e.target===document.getElementById('modal-overlay'))closeModal();}});
document.addEventListener('keydown',e=>{{if(e.key==='Escape')closeModal();}});

function scheduleRefresh(){{if(refreshTimer)clearTimeout(refreshTimer);refreshTimer=setTimeout(()=>{{fetchData();}},REFRESH_INTERVAL);}}
function startProgressBar(){{
  const bar=document.getElementById('progress-bar');progressStart=Date.now();
  if(progressTimer)clearInterval(progressTimer);
  bar.style.transition='none';bar.style.width='100%';
  progressTimer=setInterval(()=>{{
    const elapsed=Date.now()-progressStart;
    const rem=Math.max(0,1-elapsed/REFRESH_INTERVAL);
    bar.style.transition='width 1s linear';bar.style.width=(rem*100)+'%';
    if(rem<=0)clearInterval(progressTimer);
  }},1000);
}}

document.getElementById('btn-refresh').addEventListener('click',()=>{{
  const icon=document.getElementById('refresh-icon');
  icon.outerHTML='<span class="spinner" id="refresh-icon"></span>';
  if(refreshTimer)clearTimeout(refreshTimer);if(progressTimer)clearInterval(progressTimer);
  fetchData().finally(()=>{{const sp=document.getElementById('refresh-icon');if(sp)sp.outerHTML='<span id="refresh-icon">&#128260;</span>';}});
}});
document.getElementById('btn-retry').addEventListener('click',fetchData);
let searchDebounce=null;
document.getElementById('search-input').addEventListener('input',()=>{{clearTimeout(searchDebounce);searchDebounce=setTimeout(()=>{{if(appData.rows.length>0)renderCurrentView();}},300);}});
document.getElementById('filter-uf').addEventListener('change',()=>{{if(appData.rows.length>0)renderCurrentView();}});
document.getElementById('filter-func').addEventListener('change',()=>{{if(appData.rows.length>0)renderCurrentView();}});
document.getElementById('filter-region').addEventListener('change',()=>{{if(appData.rows.length>0)renderCurrentView();}});
document.getElementById('btn-clear').addEventListener('click',()=>{{
  document.getElementById('search-input').value='';
  document.getElementById('filter-uf').value='';
  document.getElementById('filter-func').value='';
  document.getElementById('filter-region').value='';
  if(appData.rows.length>0)goHome();
}});
function escapeAttr(str){{return(str||'').replace(/\\/g,'\\\\').replace(/'/g,"\\'").replace(/"/g,'&quot;').replace(/\n/g,' ');}}
fetchData();
</script>
</body>
</html>
"""

def generate_html(csv_url: str, logo_url: str, refresh_interval: int) -> str:
    return HTML_TEMPLATE.format(
        csv_url=csv_url,
        logo_url=logo_url,
        refresh_interval=refresh_interval,
    )

# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────
def main():
    print("=" * 60)
    print("GAM Farma — Gerador de Diretório HTML")
    print(f"  CSV:    {CSV_URL}")
    print(f"  Saída:  {OUTPUT_FILE}")
    print("=" * 60)

    # Opcional: validar CSV (pode ser pulado em CI para gerar HTML somente de template)
    print("\n[1/2] Validando planilha Google Sheets…")
    try:
        rows = fetch_csv(CSV_URL)
        print(f"  Planilha OK — {len(rows)} linhas")
    except Exception as e:
        print(f"  AVISO: Não foi possível validar CSV: {e}")
        print("  O HTML será gerado com leitura dinâmica (client-side).")

    print("\n[2/2] Gerando index.html…")
    html_content = generate_html(CSV_URL, LOGO_URL, REFRESH_INTERVAL_MS)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(html_content)
    size_kb = os.path.getsize(OUTPUT_FILE) / 1024
    print(f"  {OUTPUT_FILE} gerado com sucesso ({size_kb:.1f} KB)")

    print("\n✅ Concluído!")

if __name__ == "__main__":
    main()
