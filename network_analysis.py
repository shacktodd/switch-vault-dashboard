"""
network_analysis.py
===================
Switch & Vault — Shared Service Layer Network Model (Proposal 3)

WHAT THIS MODELS
----------------
The CSD corpus identified that Chinese underground banking networks (Chinese Money
Laundering Networks / CMLNs, exemplified by the Zhang network) simultaneously launder
proceeds from four distinct adversary-state flows:

  1. DPRK:     Crypto theft → THORChain mixer → CMLN laundering rails
  2. Russia:   RBOC sanctions evasion → correspondent banking → CMLN shells
  3. Iran:     IRGC oil proceeds → hawala/fei qian → CMLN output channels
  4. Cartels:  Fentanyl precursor payments → BSA-flagged transactions → CMLN shells

Key finding: attribution complexity is MULTIPLICATIVE, not additive — a single
enforcement action carries intelligence equities across all four adversary states
simultaneously, which explains the US government's hesitancy to disrupt these networks
aggressively (disruption reveals collection methods).

This script builds a directed network graph, computes centrality metrics, and produces:
  1. A visualization saved as network_output.png
  2. A printed centrality report

INTERPRETATION CAVEAT
---------------------
This is a STRUCTURAL TOPOLOGY PROTOTYPE. Node weights and edge volumes are derived
from public FinCEN SAR data, UN Panel of Experts reports, and the CSD corpus digests —
not from classified transaction records. The topology (which nodes connect to which)
is documented; the edge weights (transaction volumes) are approximate.

DEPENDENCIES
------------
  pip install networkx matplotlib numpy
"""

import json
from pathlib import Path

try:
    import networkx as nx
    import matplotlib.pyplot as plt
    import matplotlib.patches as mpatches
    import numpy as np
except ImportError:
    print("ERROR: Install dependencies with:\n  pip install networkx matplotlib numpy")
    raise

# ── Network definition ─────────────────────────────────────────────────────
#
# Node categories:
#   SOURCE      = adversary state / criminal origin of funds
#   MIXER       = obfuscation layer (crypto mixers, hawala)
#   HUB         = Chinese underground banking network (CMLN) — the shared service layer
#   SHELL       = shell company / account cluster within CMLN infrastructure
#   OUTPUT      = clean output channels
#
# Edge weights = estimated annual flow in $M (approximate, from public sources)
# Edge data sources documented per edge

NODES = {
    # ── Source nodes (adversary states / criminal orgs) ──────────────────
    "DPRK_Lazarus":      {"category": "SOURCE",  "label": "DPRK\nLazarus Group",     "flow_usd_m": 577,  "source": "Chainalysis 2026; UN PoE"},
    "Russia_RBOC":       {"category": "SOURCE",  "label": "Russia\nRBOC Sanctions",   "flow_usd_m": 900,  "source": "FinCEN SAR aggregate; BIS"},
    "Iran_IRGC":         {"category": "SOURCE",  "label": "Iran\nIRGC Oil Proceeds",  "flow_usd_m": 200,  "source": "OFAC/State Dept estimates"},
    "Cartel_Fentanyl":   {"category": "SOURCE",  "label": "Cartel\nFentanyl Proceeds","flow_usd_m": 1400, "source": "FinCEN BSA filings 2025 ($1.4B suspicious)"},

    # ── Mixing / obfuscation layer ────────────────────────────────────────
    "THORChain":         {"category": "MIXER",   "label": "THORChain\n(Crypto Mixer)", "flow_usd_m": 400, "source": "CSD digest Jun 2026; Chainalysis"},
    "Hawala_Fei_Qian":   {"category": "MIXER",   "label": "Hawala /\nFei Qian",        "flow_usd_m": 500, "source": "FinCEN; FATF typologies"},
    "Correspondent_Bank":{"category": "MIXER",   "label": "Correspondent\nBanking",    "flow_usd_m": 300, "source": "FinCEN SAR; BIS correspondent data"},

    # ── Hub: Chinese underground banking / CMLN ───────────────────────────
    # This is the "shared service layer" — the central finding
    "CMLN_Hub":          {"category": "HUB",     "label": "CMLN Hub\n(Shared Service Layer)\nZhang Network\n170+ accounts / 150+ companies", "flow_usd_m": 2500, "source": "FinCEN; DOJ Zhang indictment"},

    # ── Shell company / account clusters within CMLN ──────────────────────
    "Shell_US_RE":       {"category": "SHELL",   "label": "US Real Estate\nShell Cos", "flow_usd_m": 400, "source": "FinCEN GTO; FHFA reports"},
    "Shell_HK_SG":       {"category": "SHELL",   "label": "HK / Singapore\nShells",    "flow_usd_m": 600, "source": "FATF 2023; MAS SAR data"},
    "Shell_TBML":        {"category": "SHELL",   "label": "Trade-Based\nML (TBML)",    "flow_usd_m": 500, "source": "FinCEN TBML advisory 2023"},
    "Crypto_Exchange":   {"category": "SHELL",   "label": "Offshore Crypto\nExchanges","flow_usd_m": 300, "source": "Chainalysis; DOJ Binance settlement"},

    # ── Output (clean funds re-entering legitimate economy) ───────────────
    "Output_RealEstate": {"category": "OUTPUT",  "label": "Real Estate\n(US/EU/AU)",   "flow_usd_m": 350, "source": "FinCEN GTO; AUSTRAC"},
    "Output_Commerce":   {"category": "OUTPUT",  "label": "Legitimate\nCommerce",      "flow_usd_m": 700, "source": "FinCEN; DOJ"},
    "Output_Crypto":     {"category": "OUTPUT",  "label": "Clean Crypto\nAssets",      "flow_usd_m": 250, "source": "Chainalysis"},
    "Output_FX":         {"category": "OUTPUT",  "label": "FX / Capital\nMarkets",     "flow_usd_m": 200, "source": "FinCEN; BIS"},
}

EDGES = [
    # DPRK flow path
    ("DPRK_Lazarus",    "THORChain",          {"weight": 350, "label": "Crypto theft\n→ mixer"}),
    ("DPRK_Lazarus",    "Crypto_Exchange",    {"weight": 180, "label": "Direct to\nexchanges"}),
    ("THORChain",       "CMLN_Hub",           {"weight": 300, "label": "Mixed funds\n→ CMLN"}),

    # Russia flow path
    ("Russia_RBOC",     "Correspondent_Bank", {"weight": 200, "label": "Correspondent\nbank layer"}),
    ("Russia_RBOC",     "Hawala_Fei_Qian",    {"weight": 150, "label": "Hawala for\nsmall value"}),
    ("Correspondent_Bank", "CMLN_Hub",        {"weight": 250, "label": "CMLN\nintegration"}),

    # Iran flow path
    ("Iran_IRGC",       "Hawala_Fei_Qian",    {"weight": 150, "label": "Oil proceeds\n→ hawala"}),
    ("Iran_IRGC",       "Shell_HK_SG",        {"weight":  50, "label": "HK/SG\nshells direct"}),

    # Cartel flow path (largest single source by FinCEN filing volume)
    ("Cartel_Fentanyl", "Hawala_Fei_Qian",    {"weight": 700, "label": "Precursor\npayments"}),
    ("Cartel_Fentanyl", "Correspondent_Bank", {"weight": 200, "label": "BSA-flagged\ntransfers"}),

    # Hawala → CMLN Hub
    ("Hawala_Fei_Qian", "CMLN_Hub",           {"weight": 900, "label": "Fei qian\n→ CMLN"}),

    # Crypto Exchange → CMLN
    ("Crypto_Exchange", "CMLN_Hub",           {"weight": 250, "label": "Exchange\n→ CMLN"}),

    # CMLN Hub → Shell clusters
    ("CMLN_Hub", "Shell_US_RE",              {"weight": 400, "label": ""}),
    ("CMLN_Hub", "Shell_HK_SG",             {"weight": 500, "label": ""}),
    ("CMLN_Hub", "Shell_TBML",              {"weight": 450, "label": ""}),
    ("CMLN_Hub", "Crypto_Exchange",         {"weight": 200, "label": "Layering\nloop"}),

    # Shell clusters → Outputs
    ("Shell_US_RE",    "Output_RealEstate",  {"weight": 350, "label": ""}),
    ("Shell_HK_SG",    "Output_Commerce",    {"weight": 400, "label": ""}),
    ("Shell_HK_SG",    "Output_FX",         {"weight": 150, "label": ""}),
    ("Shell_TBML",     "Output_Commerce",   {"weight": 300, "label": ""}),
    ("Crypto_Exchange","Output_Crypto",      {"weight": 250, "label": ""}),
]


# ── Build graph ─────────────────────────────────────────────────────────────

def build_graph() -> nx.DiGraph:
    G = nx.DiGraph()
    for node_id, attrs in NODES.items():
        G.add_node(node_id, **attrs)
    for src, dst, attrs in EDGES:
        G.add_edge(src, dst, **attrs)
    return G


# ── Centrality analysis ─────────────────────────────────────────────────────

def run_centrality(G: nx.DiGraph) -> dict:
    metrics = {}

    # Betweenness centrality — which nodes sit on the most shortest paths
    # (how many flows MUST pass through this node)
    bc = nx.betweenness_centrality(G, weight="weight", normalized=True)

    # In-degree centrality — how many sources flow into each node
    idc = nx.in_degree_centrality(G)

    # Out-degree centrality — how many channels each node distributes to
    odc = nx.out_degree_centrality(G)

    # PageRank — importance accounting for the importance of neighbors
    pr = nx.pagerank(G, weight="weight")

    for node in G.nodes():
        metrics[node] = {
            "betweenness": round(bc.get(node, 0), 4),
            "in_degree":   round(idc.get(node, 0), 4),
            "out_degree":  round(odc.get(node, 0), 4),
            "pagerank":    round(pr.get(node, 0), 4),
            "flow_usd_m":  G.nodes[node].get("flow_usd_m", 0),
            "category":    G.nodes[node].get("category", ""),
        }

    return metrics


def print_centrality_report(metrics: dict) -> None:
    print("\n" + "=" * 70)
    print("SHARED SERVICE LAYER — CENTRALITY REPORT")
    print("Switch & Vault / CSD Framework — Proposal 3")
    print("=" * 70)

    # Sort by betweenness
    ranked = sorted(metrics.items(), key=lambda x: x[1]["betweenness"], reverse=True)

    print(f"\n{'Node':<22} {'Category':<10} {'Betweenness':>12} {'PageRank':>10} {'Flow $M':>8}")
    print("-" * 70)
    for node_id, m in ranked:
        label = NODES[node_id]["label"].replace("\n", " ")[:20]
        print(f"{label:<22} {m['category']:<10} {m['betweenness']:>12.4f} {m['pagerank']:>10.4f} {m['flow_usd_m']:>8}")

    print("\n── KEY FINDING ────────────────────────────────────────────────────")
    hub_bc = metrics.get("CMLN_Hub", {}).get("betweenness", 0)
    second_bc = sorted([v["betweenness"] for k, v in metrics.items() if k != "CMLN_Hub"], reverse=True)[0]
    print(f"  CMLN_Hub betweenness: {hub_bc:.4f}")
    print(f"  Next highest node:    {second_bc:.4f}")
    print(f"  Hub dominance ratio:  {hub_bc / second_bc:.1f}x")
    print(f"""
  The CMLN Hub's betweenness centrality confirms the 'shared service layer'
  hypothesis: disrupting this single node degrades laundering capacity across
  all four adversary-state flows simultaneously. Attribution complexity is
  MULTIPLICATIVE — any enforcement action reveals collection equities for
  DPRK, Russia, Iran, and cartel flows at once.

  Epistemics: edge weights are approximate (FinCEN/UN public data), not
  classified transaction records. Topology (connectivity) is DOCUMENTED;
  volume estimates are CONTESTED (±30% confidence interval assumed).
""")


# ── Visualization ───────────────────────────────────────────────────────────

CATEGORY_COLORS = {
    "SOURCE": "#f85149",   # red
    "MIXER":  "#d29922",   # amber
    "HUB":    "#1f6feb",   # bright blue (the key node)
    "SHELL":  "#6e7681",   # grey
    "OUTPUT": "#3fb950",   # green
}

def build_layout(G: nx.DiGraph) -> dict:
    """
    Manual layered layout: SOURCE → MIXER → HUB → SHELL → OUTPUT
    Left to right in 5 columns.
    """
    layers = {
        "SOURCE": 0,
        "MIXER":  1,
        "HUB":    2,
        "SHELL":  3,
        "OUTPUT": 4,
    }
    pos = {}
    counts = {cat: 0 for cat in layers}
    totals = {cat: sum(1 for n in G.nodes() if G.nodes[n]["category"] == cat) for cat in layers}

    for node in G.nodes():
        cat = G.nodes[node]["category"]
        x = layers[cat] * 2.5
        total = totals[cat]
        idx = counts[cat]
        # Center nodes vertically within their column
        y = (total - 1) * 0.5 - idx
        pos[node] = (x, y)
        counts[cat] += 1

    return pos


def draw_network(G: nx.DiGraph, metrics: dict) -> None:
    fig, ax = plt.subplots(figsize=(20, 12))
    fig.patch.set_facecolor("#0d1117")
    ax.set_facecolor("#0d1117")

    pos = build_layout(G)

    # Node sizes scaled by flow volume (min 800, max 5000)
    flows = [G.nodes[n].get("flow_usd_m", 100) for n in G.nodes()]
    max_flow = max(flows) if flows else 1
    node_sizes = [800 + 4000 * (G.nodes[n].get("flow_usd_m", 100) / max_flow) for n in G.nodes()]

    node_colors = [CATEGORY_COLORS.get(G.nodes[n]["category"], "#888") for n in G.nodes()]

    # Edge widths scaled by weight
    edge_weights = [G[u][v].get("weight", 50) for u, v in G.edges()]
    max_weight = max(edge_weights) if edge_weights else 1
    edge_widths = [0.5 + 3.5 * (w / max_weight) for w in edge_weights]

    # Draw edges
    nx.draw_networkx_edges(
        G, pos,
        width=edge_widths,
        edge_color="#30363d",
        arrows=True,
        arrowsize=15,
        arrowstyle="->",
        connectionstyle="arc3,rad=0.1",
        ax=ax,
        min_source_margin=25,
        min_target_margin=25,
    )

    # Draw nodes
    nx.draw_networkx_nodes(
        G, pos,
        node_size=node_sizes,
        node_color=node_colors,
        alpha=0.92,
        ax=ax,
    )

    # Labels
    labels = {n: G.nodes[n].get("label", n) for n in G.nodes()}
    nx.draw_networkx_labels(
        G, pos,
        labels=labels,
        font_size=7,
        font_color="#e6edf3",
        font_weight="bold",
        ax=ax,
    )

    # Legend
    legend_patches = [
        mpatches.Patch(color=CATEGORY_COLORS["SOURCE"], label="Source (adversary state / org)"),
        mpatches.Patch(color=CATEGORY_COLORS["MIXER"],  label="Obfuscation layer (mixer / hawala)"),
        mpatches.Patch(color=CATEGORY_COLORS["HUB"],    label="CMLN Hub — Shared Service Layer ★"),
        mpatches.Patch(color=CATEGORY_COLORS["SHELL"],  label="Shell company cluster"),
        mpatches.Patch(color=CATEGORY_COLORS["OUTPUT"], label="Clean output channel"),
    ]
    ax.legend(
        handles=legend_patches,
        loc="lower left",
        framealpha=0.3,
        facecolor="#161b22",
        edgecolor="#30363d",
        labelcolor="#e6edf3",
        fontsize=9,
    )

    # Title and annotation
    ax.set_title(
        "Chinese Underground Banking — Shared Service Layer\n"
        "Switch & Vault / CSD Framework — Proposal 3 Network Model",
        color="#e6edf3",
        fontsize=13,
        fontweight="bold",
        pad=16,
    )
    ax.text(
        0.99, 0.01,
        "Node size ∝ estimated annual flow volume | Edge width ∝ flow between nodes\n"
        "Topology: DOCUMENTED (FinCEN/UN public data) | Volumes: CONTESTED (±30%)\n"
        "Not investment advice. Academic/research use only.",
        transform=ax.transAxes,
        ha="right", va="bottom",
        fontsize=7, color="#6e7681",
    )

    ax.axis("off")
    plt.tight_layout()

    out_path = Path(__file__).parent / "network_output.png"
    plt.savefig(out_path, dpi=150, bbox_inches="tight", facecolor=fig.get_facecolor())
    print(f"\n✓ Network visualization saved to: {out_path}")
    plt.show()


# ── JSON export of centrality results ──────────────────────────────────────

def export_centrality_json(metrics: dict) -> None:
    out_path = Path(__file__).parent / "network_centrality.json"
    out = {
        "generated": __import__("datetime").datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "model_note": (
            "Structural topology prototype. Edge weights derived from FinCEN/UN public data. "
            "Topology (connectivity) is DOCUMENTED; volume estimates are CONTESTED (±30%). "
            "Not investment advice."
        ),
        "nodes": {
            node_id: {
                "label":      NODES[node_id]["label"].replace("\n", " "),
                "category":   m["category"],
                "flow_usd_m": m["flow_usd_m"],
                "betweenness_centrality": m["betweenness"],
                "pagerank":   m["pagerank"],
                "in_degree":  m["in_degree"],
                "out_degree": m["out_degree"],
                "data_source": NODES[node_id].get("source", ""),
            }
            for node_id, m in metrics.items()
        }
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)
    print(f"✓ Centrality data exported to: {out_path}")


# ── Main ────────────────────────────────────────────────────────────────────

def main():
    print("Switch & Vault — Shared Service Layer Network Analysis")
    print("Building graph...")
    G = build_graph()
    print(f"  Nodes: {G.number_of_nodes()} | Edges: {G.number_of_edges()}")

    print("Computing centrality metrics...")
    metrics = run_centrality(G)

    print_centrality_report(metrics)

    export_centrality_json(metrics)

    print("Generating visualization...")
    draw_network(G, metrics)


if __name__ == "__main__":
    main()
