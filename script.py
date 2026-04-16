#!/usr/bin/env python3
"""
script.py — Editor do arquivo index HTML (GAM Farma)
======================================================
Aplica correções cirúrgicas no HTML do diretório de representantes,
substituindo trechos específicos de JavaScript sem alterar o restante.

Uso:
    python script.py --input index-efb0fbf5.html --output index.html

Fixes aplicados:
    Fix 1 — normalizeHeader: NOME REPRESENTANTE → NOME (causa raiz do bug)
    Fix 2 — Badge: reconhece "representante comercial"
    Fix 3 — Filtro dropdown: adiciona opção Representante Comercial
    Fix 4 — Razão Social inline na tabela renderTeam
    Fix 5 — Razão Social inline nos resultados de busca
    Fix 6 — Cache-busting agressivo (timestamp + Math.random)
    Fix 7 — Refresh interval 5 min → 3 min
"""

import argparse
import sys


FIXES = [
    {
        "description": "Fix 1 — normalizeHeader: NOME REPRESENTANTE → NOME",
        "old": """function normalizeHeader(h) {
  let s = h.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toUpperCase().trim();
  s = s.replace('COORPORATIVO','CORPORATIVO').replace('COODENADOR','COORDENADOR');
  return s;
}""",
        "new": """function normalizeHeader(h) {
  let s = h.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toUpperCase().trim();
  s = s.replace('COORPORATIVO','CORPORATIVO').replace('COODENADOR','COORDENADOR');
  if (s === 'NOME REPRESENTANTE') s = 'NOME';
  return s;
}""",
        "count": 1,
    },
    {
        "description": "Fix 2 — Badge Representante Comercial",
        "old": "  if (f.includes('representante externo')) return { cls:'badge-rep', label:func||'Rep. Externo' };",
        "new": "  if (f.includes('representante comercial')) return { cls:'badge-rep', label:func||'Rep. Comercial' };\n  if (f.includes('representante externo')) return { cls:'badge-rep', label:func||'Rep. Externo' };",
        "count": 1,
    },
    {
        "description": "Fix 3 — Filtro dropdown: adicionar Representante Comercial",
        "old": '<option value="representante externo">Representante Externo</option>',
        "new": '<option value="representante comercial">Representante Comercial</option>\n      <option value="representante externo">Representante Externo</option>',
        "count": 1,
    },
    {
        "description": "Fix 4 — Razão Social inline na tabela renderTeam",
        "old": """              <td>
                <div style=\"font-weight:700;margin-bottom:4px\">${nome}</div>
                <span class=\"func-badge ${badge.cls}\">${badge.label}</span>
              </td>""",
        "new": """              <td>
                <div style=\"font-weight:700;margin-bottom:4px\">${nome}</div>
                ${(m['RAZAO SOCIAL']&&m['RAZAO SOCIAL']!=='-'&&m['RAZAO SOCIAL']!=='') ? `<div style=\"font-size:0.78em;color:#5a6a8a;font-style:italic;margin-bottom:3px\">🏢 ${m['RAZAO SOCIAL']}</div>` : ''}
                <span class=\"func-badge ${badge.cls}\">${badge.label}</span>
              </td>""",
        "count": 1,
    },
    {
        "description": "Fix 5 — Razão Social inline nos resultados de busca",
        "old": "              <td><strong>${nome}</strong></td>",
        "new": """              <td>
                <strong>${nome}</strong>
                ${(r['RAZAO SOCIAL']&&r['RAZAO SOCIAL']!=='-'&&r['RAZAO SOCIAL']!=='') ? `<div style=\"font-size:0.78em;color:#5a6a8a;font-style:italic;margin-top:2px\">🏢 ${r['RAZAO SOCIAL']}</div>` : ''}
              </td>""",
        "count": 1,
    },
    {
        "description": "Fix 6 — Cache-busting agressivo (timestamp + random)",
        "old": "const url = `${CSV_URL}&cb=${Date.now()}`;",
        "new": "const url = `${CSV_URL}&cb=${Date.now()}_${Math.random().toString(36).slice(2)}`;",
        "count": 1,
    },
    {
        "description": "Fix 7 — Refresh interval 5 min → 3 min",
        "old": "const REFRESH_INTERVAL = 5 * 60 * 1000; // 5 minutes",
        "new": "const REFRESH_INTERVAL = 3 * 60 * 1000; // 3 minutes",
        "count": 1,
    },
]


def load_file(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def save_file(path, content):
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def apply_fixes(content):
    all_ok = True
    for fix in FIXES:
        desc  = fix["description"]
        old   = fix["old"]
        new   = fix["new"]
        count = fix.get("count", 1)
        if old not in content:
            print(f"  ⚠️  Trecho não encontrado — '{desc}' não foi aplicado.")
            all_ok = False
            continue
        content = content.replace(old, new, count)
        print(f"  ✅ {desc}")
    return content, all_ok


def main():
    parser = argparse.ArgumentParser(
        description="Aplica correções no HTML do diretório de representantes GAM Farma."
    )
    parser.add_argument("--input",  default="index-efb0fbf5.html")
    parser.add_argument("--output", default="index.html")
    args = parser.parse_args()

    print(f"\n📂 Lendo: {args.input}")
    try:
        content = load_file(args.input)
    except FileNotFoundError:
        print(f"  ❌ Arquivo não encontrado: {args.input}")
        sys.exit(1)

    print(f"\n🔧 Aplicando fixes...")
    content, all_ok = apply_fixes(content)

    print(f"\n💾 Salvando: {args.output}")
    save_file(args.output, content)

    status = "✅" if all_ok else "⚠️ "
    print(f"\n{status} Concluído! ({len(content):,} caracteres)")
    if not all_ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
