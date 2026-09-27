import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

DATA_DIR = Path(__file__).resolve().parents[2] / "data"


def build_nodes(catalog: list[dict], customers: list[dict]) -> list[dict]:
    nodes = []
    for sku in catalog:
        nodes.append({
            "id": sku["sku_id"],
            "label": "SKU",
            "properties": {
                "name": sku["name"],
                "category": sku["category"],
                "list_price": sku["list_price"],
                "discontinued": sku["discontinued"],
                "in_stock": sku["in_stock"],
            },
        })

    for category in sorted({sku["category"] for sku in catalog}):
        nodes.append({"id": category, "label": "Category", "properties": {}})

    for customer in customers:
        nodes.append({
            "id": customer["customer_id"],
            "label": "Customer",
            "properties": {"name": customer["name"], "account_tier": customer["account_tier"]},
        })
        for contract in customer["contracts"]:
            nodes.append({
                "id": contract["contract_id"],
                "label": "Contract",
                "properties": {
                    "discount_category": contract["discount_category"],
                    "effective_from": contract["effective_from"],
                    "effective_to": contract["effective_to"],
                },
            })

    return nodes


def build_edges(catalog: list[dict], customers: list[dict]) -> list[dict]:
    edges = []
    for sku in catalog:
        if sku["discontinued"] and sku["replaced_by"]:
            edges.append({"from": sku["sku_id"], "to": sku["replaced_by"], "type": "REPLACED_BY", "properties": {}})
        for required_id in sku["requires"]:
            edges.append({"from": sku["sku_id"], "to": required_id, "type": "REQUIRES", "properties": {}})
        edges.append({"from": sku["sku_id"], "to": sku["category"], "type": "BELONGS_TO", "properties": {}})

    for customer in customers:
        for contract in customer["contracts"]:
            edges.append({
                "from": customer["customer_id"],
                "to": contract["contract_id"],
                "type": "HAS_CONTRACT",
                "properties": {},
            })
            for category in contract["covered_categories"]:
                edges.append({
                    "from": contract["contract_id"],
                    "to": category,
                    "type": "COVERS",
                    "properties": {},
                })

    return edges


def write_graph(nodes: list[dict], edges: list[dict], nodes_path: Path, edges_path: Path, force: bool = False) -> None:
    for path in (nodes_path, edges_path):
        if path.exists() and not force:
            raise FileExistsError(f"{path} already exists; pass --force to overwrite")
    nodes_path.parent.mkdir(parents=True, exist_ok=True)
    edges_path.parent.mkdir(parents=True, exist_ok=True)
    nodes_path.write_text(json.dumps(nodes, indent=2), encoding="utf-8")
    edges_path.write_text(json.dumps(edges, indent=2), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Export catalog/customer data to graph nodes and edges")
    parser.add_argument("--catalog", type=Path, default=DATA_DIR / "catalog.json")
    parser.add_argument("--customers", type=Path, default=DATA_DIR / "customers.json")
    parser.add_argument("--nodes-out", type=Path, default=DATA_DIR / "graph" / "nodes.json")
    parser.add_argument("--edges-out", type=Path, default=DATA_DIR / "graph" / "edges.json")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    catalog = json.loads(args.catalog.read_text(encoding="utf-8"))
    customers = json.loads(args.customers.read_text(encoding="utf-8"))
    nodes = build_nodes(catalog, customers)
    edges = build_edges(catalog, customers)
    write_graph(nodes, edges, args.nodes_out, args.edges_out, force=args.force)
    print(f"wrote {len(nodes)} nodes and {len(edges)} edges")


if __name__ == "__main__":
    main()
