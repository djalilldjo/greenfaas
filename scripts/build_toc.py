"""
Build a unified table of contents for the GreenFaaS manuscript by scanning
all paper/*.md files. Also surface structural issues: duplicate section
numbers, missing files, etc.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

PROJ = Path(__file__).resolve().parents[1]
PAPER_DIR = PROJ / "paper"

# Files we expect, in submission order.
EXPECTED = [
    "00_abstract.md",
    "01_introduction.md",
    "02_related_work.md",
    "03_motivation.md",
    "04_1_4_2_problem_formulation.md",
    "04_3_tradeoff_lemma.md",
    "04_3_9_idle_energy_addendum.md",
    "05_algorithm.md",
    "06_simulator.md",
    "07_1_real_trace_methodology.md",
    "07_2_to_7_8_evaluation.md",
    "08_discussion.md",
    "09_conclusion.md",
]


def main():
    print("=" * 72)
    print("GreenFaaS manuscript: table of contents and structural check")
    print("=" * 72)

    missing = []
    for fname in EXPECTED:
        if not (PAPER_DIR / fname).exists():
            missing.append(fname)
    if missing:
        print(f"\nMISSING files: {missing}")
        sys.exit(1)
    else:
        print("\nAll expected files present.\n")

    section_re = re.compile(r"^(#{1,3})\s+(.+)$")
    seen_numbers = {}
    total_lines = 0
    total_words = 0

    for fname in EXPECTED:
        path = PAPER_DIR / fname
        lines = path.read_text().splitlines()
        n_lines = len(lines)
        n_words = sum(len(line.split()) for line in lines)
        total_lines += n_lines
        total_words += n_words
        print(f"  {fname:<45} {n_lines:>5} lines  {n_words:>6,} words")
        for ln in lines:
            m = section_re.match(ln)
            if m:
                level = len(m.group(1))
                header = m.group(2).strip()
                indent = "    " * level
                print(f"  {indent}§ {header}")
                # Check for duplicate section numbers (e.g. two "4.3")
                num_m = re.match(r"^(\d+(?:\.\d+)*)\s", header)
                if num_m:
                    num = num_m.group(1)
                    if num in seen_numbers and seen_numbers[num] != fname:
                        print(f"  {indent}  ** WARNING: section {num} also "
                              f"defined in {seen_numbers[num]}")
                    seen_numbers[num] = fname

    print()
    print(f"Total: {total_lines:,} lines, {total_words:,} words across {len(EXPECTED)} files.")
    print(f"At ~250 words / page (single-column), this is approximately "
          f"{total_words // 250} pages of prose.")
    print(f"At ~500 words / page (double-column conference format), approximately "
          f"{total_words // 500} pages.")


if __name__ == "__main__":
    main()
