"""
Renders the AttackChain Advisor pipeline diagrams as standalone PNG files:
  1. overall_pipeline.png      — observation -> A -> B -> C -> D -> response
  2. per_person_tasks.png      — each person's 6-task sequence, 4 lanes

Output written to: experimental data/figures/
"""

from pathlib import Path

import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

OUT_DIR = Path(__file__).parent / "experimental data" / "figures"
OUT_DIR.mkdir(parents=True, exist_ok=True)


def box(ax, x, y, w, h, title, lines, face, edge, title_color="black"):
    b = FancyBboxPatch(
        (x, y), w, h, boxstyle="round,pad=0.02,rounding_size=0.05",
        linewidth=1.4, edgecolor=edge, facecolor=face,
    )
    ax.add_patch(b)
    ax.text(x + w / 2, y + h - 0.18, title, ha="center", va="top",
             fontsize=9.5, fontweight="bold", color=title_color)
    for i, line in enumerate(lines):
        ax.text(x + w / 2, y + h - 0.45 - i * 0.22, line, ha="center", va="top", fontsize=7.6)


def arrow(ax, x1, y1, x2, y2):
    a = FancyArrowPatch((x1, y1), (x2, y2), arrowstyle="-|>", mutation_scale=14,
                         linewidth=1.3, color="#6b7280")
    ax.add_patch(a)


def fig_overall_pipeline():
    fig, ax = plt.subplots(figsize=(13, 5.5))
    ax.set_xlim(0, 13)
    ax.set_ylim(0, 5.5)
    ax.axis("off")

    box(ax, 0.2, 2.2, 1.7, 1.2, "Researcher\nobservation", ["(natural language)"], "#f3f4f6", "#9ca3af")

    box(ax, 2.3, 1.9, 2.4, 1.8, "PERSON A", [
        "Embedding Retrieval", "embed query + 41 entries", "cosine top-k match",
        "out: ranked candidates",
    ], "#dbeafe", "#3b82f6", "#1e40af")

    box(ax, 5.1, 1.9, 2.4, 1.8, "PERSON B", [
        "Quality Ranking", "weight by pass_count +", "composite score",
        "out: re-ranked + confidence",
    ], "#dcfce7", "#16a34a", "#15803d")

    box(ax, 7.9, 1.9, 2.4, 1.8, "PERSON C", [
        "Graph Traversal", "walk cross_references.json", "bidirectional, multi-hop",
        "out: attack chain path",
    ], "#fef3c7", "#d97706", "#92400e")

    box(ax, 10.7, 1.9, 1.9, 1.8, "PERSON D", [
        "LLM Synthesis", "explain reasoning,", "pitfalls, chain",
        "out: response",
    ], "#fce7f3", "#db2777", "#9d174d")

    box(ax, 10.6, 0.0, 2.1, 1.3, "Explainable\nresponse",
        ["reasoning path", "confidence + pitfalls", "full attack chain"], "#f3f4f6", "#9ca3af")

    arrow(ax, 1.9, 2.8, 2.3, 2.8)
    arrow(ax, 4.7, 2.8, 5.1, 2.8)
    arrow(ax, 7.5, 2.8, 7.9, 2.8)
    arrow(ax, 10.3, 2.8, 10.7, 2.8)
    arrow(ax, 11.65, 1.9, 11.65, 1.3)

    ax.text(0.2, 4.8, "AttackChain Advisor — Directional Pipeline", fontsize=14, fontweight="bold")
    ax.text(0.2, 0.35,
            "Sequential handoff: each stage's output is the next stage's input.\n"
            "A, B, C can be built/tested in parallel against static JSON files;\n"
            "D needs all three before final synthesis.",
            fontsize=8.2, color="#4b5563")

    fig.tight_layout()
    fig.savefig(OUT_DIR / "overall_pipeline.png", dpi=180)
    plt.close(fig)


def lane_tasks(ax, y0, label, color_face, color_edge, color_text, tasks):
    ax.text(0.1, y0 + 1.05, label, fontsize=11, fontweight="bold", color=color_text)
    x = 0.1
    w, h = 2.6, 0.95
    gap = 0.5
    positions = []
    for i, (title, sub) in enumerate(tasks):
        face = color_face if i < len(tasks) - 1 else color_edge
        box(ax, x, y0, w, h, f"{i+1}. {title}", [sub], face, color_text)
        positions.append((x, y0, w, h))
        x += w + gap

    for i in range(len(positions) - 1):
        x1, y1, w1, h1 = positions[i]
        x2, y2, w2, h2 = positions[i + 1]
        arrow(ax, x1 + w1, y1 + h1 / 2, x2, y2 + h2 / 2)


def fig_per_person_tasks():
    fig, ax = plt.subplots(figsize=(15, 11))
    ax.set_xlim(0, 14)
    ax.set_ylim(0, 11)
    ax.axis("off")
    ax.text(0.1, 10.7, "Per-Person Task Pipelines", fontsize=15, fontweight="bold")

    lane_tasks(ax, 8.6, "PERSON A — Embedding Retrieval", "#dbeafe", "#bfdbfe", "#1e40af", [
        ("Pull text", "trigger_condition + knowledge"),
        ("embed_corpus.py", "cache vectors to disk"),
        ("embed_query()", "embed observation"),
        ("top_k_similar()", "cosine ranked candidates"),
        ("Test vs 5 examples", "confirm correct top-3"),
        ("Expose retrieve()", "hand off to B"),
    ])

    lane_tasks(ax, 6.4, "PERSON B — Quality Ranking", "#dcfce7", "#bbf7d0", "#15803d", [
        ("Load quality_metrics.json", "build id->score index"),
        ("Design composite score", "similarity + quality weight"),
        ("Write rank()", "re-sort A's top-k"),
        ("Define confidence tiers", "8/8 high vs needs-validation"),
        ("Test ranked output", "vs 5 example observations"),
        ("Document formula", "hand off to C"),
    ])

    lane_tasks(ax, 4.2, "PERSON C — Graph Traversal", "#fef3c7", "#fde68a", "#92400e", [
        ("Load cross_references.json", "build networkx DiGraph"),
        ("Write traverse(depth=2)", "bidirectional edges"),
        ("Handle out-of-range IDs", "ek_0041-0253 markers"),
        ("Write suggested_chains()", "full multi-hop paths"),
        ("Test known pairs", "ek_0002->ek_0003 etc."),
        ("Expose get_chain_context()", "hand off to D"),
    ])

    lane_tasks(ax, 2.0, "PERSON D — LLM Synthesis", "#fce7f3", "#fbcfe8", "#9d174d", [
        ("Combine A+B+C", "structured input"),
        ("Design response template", "path->signal->pitfall->chain"),
        ("Write synthesis prompt", "explain why this match"),
        ("Wire main.py", "orchestrate A->B->C->D"),
        ("Build CLI/demo UI", "Streamlit or Flask"),
        ("Run all 5 examples", "final demo output"),
    ])

    fig.tight_layout()
    fig.savefig(OUT_DIR / "per_person_tasks.png", dpi=180)
    plt.close(fig)


if __name__ == "__main__":
    fig_overall_pipeline()
    fig_per_person_tasks()
    print(f"Wrote PNGs to {OUT_DIR}")
