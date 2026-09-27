import argparse
from pathlib import Path

from data_gen.catalog_gen import generate_catalog, write_catalog
from data_gen.config import DEFAULT
from data_gen.customer_gen import generate_customers, write_customers
from data_gen.graph_export import build_edges, build_nodes, write_graph


def check_output_paths_are_clear(paths: list[Path], force: bool) -> None:
    if force:
        return
    existing = [p for p in paths if p.exists()]
    if existing:
        names = ", ".join(str(p) for p in existing)
        raise FileExistsError(f"output already exists: {names}; pass --force to overwrite")


def run(data_dir: Path, force: bool = False) -> None:
    catalog_path = data_dir / "catalog.json"
    customers_path = data_dir / "customers.json"
    nodes_path = data_dir / "graph" / "nodes.json"
    edges_path = data_dir / "graph" / "edges.json"

    check_output_paths_are_clear([catalog_path, customers_path, nodes_path, edges_path], force)

    catalog = generate_catalog(DEFAULT)
    write_catalog(catalog, catalog_path, force=force)

    customers = generate_customers(DEFAULT, catalog)
    write_customers(customers, customers_path, force=force)

    nodes = build_nodes(catalog, customers)
    edges = build_edges(catalog, customers)
    write_graph(nodes, edges, nodes_path, edges_path, force=force)

    print(f"wrote {len(catalog)} SKUs, {len(customers)} customers, {len(nodes)} nodes, {len(edges)} edges to {data_dir}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the full Phase 1 data generation pipeline (catalog, customers, graph)")
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    run(args.data_dir, force=args.force)


if __name__ == "__main__":
    main()
