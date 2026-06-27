"""
Visualise the three datasets in `experimental data/experimental data/`:
  - experiential_knowledge_41.json  (41 knowledge entries, layer-0 subset)
  - quality_metrics.json            (per-entry quality checklist + aggregates)
  - cross_references.json           (complementary pairs / suggested chains)

Produces a set of PNG figures in `experimental data/figures/`.
"""

import json
from collections import Counter
from pathlib import Path

import matplotlib.pyplot as plt
import networkx as nx
import pandas as pd

DATA_DIR = Path(__file__).parent / "experimental data" / "experimental data"
OUT_DIR = Path(__file__).parent / "experimental data" / "figures"
OUT_DIR.mkdir(parents=True, exist_ok=True)


def load_json(name):
    with open(DATA_DIR / name, "r", encoding="utf-8") as f:
        return json.load(f)


def fig_category_distribution(knowledge):
    counts = Counter(item["category"] for item in knowledge)
    fig, ax = plt.subplots(figsize=(7, 5))
    categories = sorted(counts, key=counts.get, reverse=True)
    ax.bar(categories, [counts[c] for c in categories], color="#4472C4")
    ax.set_title("Knowledge entries by category (n=41)")
    ax.set_ylabel("count")
    ax.tick_params(axis="x", rotation=30)
    fig.tight_layout()
    fig.savefig(OUT_DIR / "01_category_distribution.png", dpi=150)
    plt.close(fig)


def fig_confidence_and_shelf_life(knowledge):
    confidences = [item.get("confidence") for item in knowledge if item.get("confidence")]
    shelf_lives = [item.get("shelf_life") for item in knowledge if item.get("shelf_life")]

    fig, axes = plt.subplots(1, 2, figsize=(11, 5))

    conf_counts = Counter(confidences)
    order = sorted(conf_counts, key=lambda k: str(k))
    axes[0].bar(order, [conf_counts[k] for k in order], color="#ED7D31")
    axes[0].set_title("Confidence level distribution")
    axes[0].tick_params(axis="x", rotation=30)

    shelf_counts = Counter(shelf_lives)
    order2 = sorted(shelf_counts, key=lambda k: str(k))
    axes[1].bar(order2, [shelf_counts[k] for k in order2], color="#70AD47")
    axes[1].set_title("Shelf-life estimate distribution")
    axes[1].tick_params(axis="x", rotation=30)

    fig.tight_layout()
    fig.savefig(OUT_DIR / "02_confidence_shelf_life.png", dpi=150)
    plt.close(fig)


def fig_quality_pass_rates(quality):
    rates = quality["quality_checklist"]["check_pass_rates"]
    fig, ax = plt.subplots(figsize=(8, 5))
    names = list(rates.keys())
    values = [rates[k] for k in names]
    ax.barh(names, values, color="#264478")
    ax.set_xlim(0, 1.05)
    ax.set_xlabel("pass rate")
    ax.set_title("Quality checklist pass rates (n=41)")
    for i, v in enumerate(values):
        ax.text(v + 0.01, i, f"{v:.2f}", va="center")
    fig.tight_layout()
    fig.savefig(OUT_DIR / "03_quality_pass_rates.png", dpi=150)
    plt.close(fig)


def fig_quality_aggregates(quality):
    layer0 = quality["layer0"]
    metrics = {
        "avg_derivability": layer0["avg_derivability"],
        "avg_condition_richness": layer0["avg_condition_richness"],
        "avg_abstraction_quality": layer0["avg_abstraction_quality"],
        "avg_composite": layer0["avg_composite"],
    }
    fig, ax = plt.subplots(figsize=(6, 5))
    ax.bar(metrics.keys(), metrics.values(), color="#9E480E")
    ax.set_ylim(0, 1)
    ax.set_title("Repository-level quality aggregates")
    ax.tick_params(axis="x", rotation=20)
    for i, (k, v) in enumerate(metrics.items()):
        ax.text(i, v + 0.02, f"{v:.3f}", ha="center")
    fig.tight_layout()
    fig.savefig(OUT_DIR / "04_quality_aggregates.png", dpi=150)
    plt.close(fig)


def fig_pass_count_histogram(quality):
    items = quality["quality_checklist"]["items"]
    pass_counts = [item["pass_count"] for item in items]
    fig, ax = plt.subplots(figsize=(6, 5))
    counts = Counter(pass_counts)
    order = sorted(counts)
    ax.bar(order, [counts[k] for k in order], color="#636363")
    ax.set_xlabel("checks passed (out of 8)")
    ax.set_ylabel("number of entries")
    ax.set_title("Distribution of per-entry quality pass counts")
    fig.tight_layout()
    fig.savefig(OUT_DIR / "05_pass_count_histogram.png", dpi=150)
    plt.close(fig)


def fig_cross_reference_graph(cross_refs, knowledge):
    cat_by_id = {item["id"]: item["category"] for item in knowledge}
    color_map = {
        "chain_pattern": "#4472C4",
        "signal_interpretation": "#ED7D31",
        "tactical_priority": "#70AD47",
        "bypass_technique": "#FFC000",
        "pitfall": "#A5A5A5",
    }

    g = nx.DiGraph()
    for pair in cross_refs["complementary_pairs"]:
        a, b = pair["a"]["id"], pair["b"]["id"]
        g.add_node(a, category=pair["a"]["category"])
        g.add_node(b, category=pair["b"]["category"])
        g.add_edge(a, b)

    # restrict to nodes within the 41-entry layer-0 subset for clarity
    subset_ids = set(cat_by_id.keys())
    nodes_in_subset = [n for n in g.nodes if n in subset_ids]
    g = g.subgraph(nodes_in_subset).copy()

    fig, ax = plt.subplots(figsize=(10, 8))
    pos = nx.spring_layout(g, seed=42, k=0.6)
    node_colors = [color_map.get(cat_by_id.get(n, ""), "#000000") for n in g.nodes]
    nx.draw_networkx_nodes(g, pos, node_color=node_colors, node_size=350, ax=ax)
    nx.draw_networkx_edges(g, pos, arrows=True, arrowsize=12, ax=ax)
    nx.draw_networkx_labels(g, pos, font_size=7, ax=ax)

    handles = [
        plt.Line2D([0], [0], marker="o", color="w", label=cat, markerfacecolor=color, markersize=9)
        for cat, color in color_map.items()
    ]
    ax.legend(handles=handles, loc="upper right", fontsize=8)
    ax.set_title("Suggested attack chains among layer-0 entries (cross_references.json)")
    ax.axis("off")
    fig.tight_layout()
    fig.savefig(OUT_DIR / "06_cross_reference_graph.png", dpi=150)
    plt.close(fig)


def fig_confidence_by_category(knowledge):
    df = pd.DataFrame(knowledge)[["category", "confidence"]].dropna()
    table = pd.crosstab(df["category"], df["confidence"])
    fig, ax = plt.subplots(figsize=(8, 5))
    table.plot(kind="bar", stacked=True, ax=ax, colormap="viridis")
    ax.set_title("Confidence level by category")
    ax.set_ylabel("count")
    ax.tick_params(axis="x", rotation=30)
    fig.tight_layout()
    fig.savefig(OUT_DIR / "07_confidence_by_category.png", dpi=150)
    plt.close(fig)


def main():
    eknowledge_raw = load_json("experiential_knowledge_41.json")
    quality = load_json("quality_metrics.json")
    cross_refs = load_json("cross_references.json")

    knowledge = eknowledge_raw.get("knowledge", eknowledge_raw)
    if isinstance(knowledge, dict) and "knowledge" in knowledge:
        knowledge = knowledge["knowledge"]

    # The 41-entry layer-0 subset corresponds to ek_0000..ek_0040.
    layer0_ids = {f"ek_{i:04d}" for i in range(41)}
    layer0_knowledge = [item for item in knowledge if item.get("id") in layer0_ids] or knowledge[:41]

    fig_category_distribution(layer0_knowledge)
    fig_confidence_and_shelf_life(layer0_knowledge)
    fig_quality_pass_rates(quality)
    fig_quality_aggregates(quality)
    fig_pass_count_histogram(quality)
    fig_cross_reference_graph(cross_refs, layer0_knowledge)
    fig_confidence_by_category(layer0_knowledge)

    print(f"Wrote {len(list(OUT_DIR.glob('*.png')))} figures to {OUT_DIR}")


if __name__ == "__main__":
    main()
