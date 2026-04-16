#!/usr/bin/env python3
"""
script.py — Editor do arquivo index HTML (GAM Farma)
======================================================
Este script aplica correções cirúrgicas no HTML do mapa de equipes,
substituindo trechos específicos de JavaScript sem alterar o restante do arquivo.

Uso:
    python script.py --input index_v4.html --output index_v5.html

Fixes aplicados:
    Fix 1 — MT stateMap: garante que o estado MT exiba somente o card do Lucas
    Fix 2 — Seção orphan: oculta "Representantes sem coordenador" para MT
"""

import argparse
import sys


# ─────────────────────────────────────────────
# FIXES
# Cada fix é um dicionário com:
#   description : descrição legível do que faz
#   old         : trecho original a ser substituído
#   new         : trecho novo que substituirá o original
#   count       : quantas substituições esperar (1 = apenas a 1ª ocorrência)
# ─────────────────────────────────────────────

FIXES = [
    {
        "description": "Fix 1 — stateMap['MT'] recebe somente o grupo do Lucas",
        "old": """  // 5. Adicionar ao stateMap de MT (sem duplicata)
  if (!stateMap['MT']) stateMap['MT'] = [];
  if (!stateMap['MT'].includes(mtGroup)) stateMap['MT'].push(mtGroup);
}""",
        "new": """  // 5. stateMap de MT recebe SOMENTE o grupo do Lucas (sem outros cards)
  stateMap['MT'] = [mtGroup];
}""",
        "count": 1,
    },
    {
        "description": "Fix 2 — Ocultar seção orphan para o estado MT",
        "old": "  if (orphanMembers.length > 0) {",
        "new": "  if (orphanMembers.length > 0 && uf !== 'MT') {",
        "count": 1,
    },
]


# ─────────────────────────────────────────────
# FUNÇÕES
# ─────────────────────────────────────────────

def load_file(path: str) -> str:
    """Lê o arquivo HTML e retorna seu conteúdo como string."""
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def save_file(path: str, content: str) -> None:
    """Salva o conteúdo modificado em um novo arquivo."""
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def apply_fixes(content: str) -> str:
    """Aplica todos os fixes definidos em FIXES e retorna o conteúdo modificado."""
    for fix in FIXES:
        desc  = fix["description"]
        old   = fix["old"]
        new   = fix["new"]
        count = fix.get("count", 1)

        if old not in content:
            print(f"  ⚠️  Trecho não encontrado — '{desc}' não foi aplicado.")
            continue

        content = content.replace(old, new, count)
        print(f"  ✅ {desc}")

    return content


def main():
    parser = argparse.ArgumentParser(
        description="Aplica correções no HTML do mapa de equipes GAM Farma."
    )
    parser.add_argument(
        "--input",
        default="index_v4.html",
        help="Arquivo HTML de entrada (padrão: index_v4.html)"
    )
    parser.add_argument(
        "--output",
        default="index_v5.html",
        help="Arquivo HTML de saída (padrão: index_v5.html)"
    )
    args = parser.parse_args()

    print(f"\n📂 Lendo: {args.input}")
    try:
        content = load_file(args.input)
    except FileNotFoundError:
        print(f"  ❌ Arquivo não encontrado: {args.input}")
        sys.exit(1)

    print(f"\n🔧 Aplicando fixes...")
    content = apply_fixes(content)

    print(f"\n💾 Salvando: {args.output}")
    save_file(args.output, content)

    print(f"\n✅ Concluído! ({len(content):,} caracteres)")


if __name__ == "__main__":
    main()
