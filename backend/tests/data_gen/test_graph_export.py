from data_gen.catalog_gen import generate_catalog
from data_gen.config import Config
from data_gen.customer_gen import generate_customers
from data_gen.graph_export import build_edges, build_nodes


def _dataset():
    config = Config(seed=42, sku_count=650, customer_count=125, scenarios_per_type=10)
    catalog = generate_catalog(config)
    customers = generate_customers(config, catalog)
    return catalog, customers


def test_one_sku_node_per_catalog_entry():
    catalog, customers = _dataset()
    nodes = build_nodes(catalog, customers)
    sku_nodes = [n for n in nodes if n["label"] == "SKU"]
    assert len(sku_nodes) == len(catalog)


def test_one_customer_node_per_customer():
    catalog, customers = _dataset()
    nodes = build_nodes(catalog, customers)
    customer_nodes = [n for n in nodes if n["label"] == "Customer"]
    assert len(customer_nodes) == len(customers)


def test_one_belongs_to_edge_per_sku():
    catalog, customers = _dataset()
    edges = build_edges(catalog, customers)
    belongs_to = [e for e in edges if e["type"] == "BELONGS_TO"]
    assert len(belongs_to) == len(catalog)


def test_has_contract_edge_per_customer_contract():
    catalog, customers = _dataset()
    edges = build_edges(catalog, customers)
    has_contract = [e for e in edges if e["type"] == "HAS_CONTRACT"]
    total_contracts = sum(len(c["contracts"]) for c in customers)
    assert len(has_contract) == total_contracts


def test_replaced_by_edges_match_discontinued_skus():
    catalog, customers = _dataset()
    edges = build_edges(catalog, customers)
    replaced_by_edges = [e for e in edges if e["type"] == "REPLACED_BY"]
    discontinued_with_target = [s for s in catalog if s["discontinued"] and s["replaced_by"]]
    assert len(replaced_by_edges) == len(discontinued_with_target)


def test_covers_edges_point_to_covered_categories():
    catalog, customers = _dataset()
    edges = build_edges(catalog, customers)
    covers_edges = [e for e in edges if e["type"] == "COVERS"]
    total_covered = sum(len(ctr["covered_categories"]) for c in customers for ctr in c["contracts"])
    assert len(covers_edges) == total_covered
