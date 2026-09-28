from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.graph.repository import drop_namespace, ensure_constraints, merge_edges, merge_nodes
from app.reference_data.repository import (
    all_contacts, all_contracts, all_customers, all_families, all_projects, all_requirements, all_sites, all_skus,
    reference_fingerprint,
)
from core.graph.client import GraphClient


def _edge(source: str, target: str) -> dict:
    return {"from": source, "to": target, "props": {}}


def rebuild_reference_graph(session: Session, client: GraphClient, ns: str) -> None:
    """Wipe and reload the reference part of one namespace from Postgres. Idempotent."""
    skus = all_skus(session)
    contracts = all_contracts(session)
    projects = all_projects(session)
    contacts = all_contacts(session)

    drop_namespace(client, ns)
    ensure_constraints(client)

    # A contract can cover a category no SKU uses; the node must exist for the COVERS edge.
    categories = sorted({s.category for s in skus} | {c for k in contracts for c in k.covered_categories})
    merge_nodes(client, ns, "PricingCategory", [{"id": c, "props": {}} for c in categories])
    merge_nodes(client, ns, "ProductFamily", [{"id": f.family_id, "props": {"name": f.name}} for f in all_families(session)])
    merge_nodes(client, ns, "SKU", [
        {"id": s.sku_id, "props": {
            "name": s.name, "category": s.category, "list_price": s.list_price,
            "discontinued": s.discontinued, "in_stock": s.in_stock,
        }} for s in skus
    ])
    merge_nodes(client, ns, "Customer", [
        {"id": c.customer_id, "props": {"name": c.name, "account_tier": c.account_tier}} for c in all_customers(session)
    ])
    merge_nodes(client, ns, "Person", [
        {"id": p.contact_id, "props": {"name": p.name, "email": p.email, "phone": p.phone}} for p in contacts
    ])
    merge_nodes(client, ns, "Contract", [
        {"id": k.contract_id, "props": {
            "discount_pct": k.discount_pct, "discount_category": k.discount_category,
            "effective_from": k.effective_from.isoformat(), "effective_to": k.effective_to.isoformat(),
        }} for k in contracts
    ])
    merge_nodes(client, ns, "Site", [
        {"id": s.site_id, "props": {"address": s.address, "zip": s.zip}} for s in all_sites(session)
    ])
    merge_nodes(client, ns, "Project", [{"id": p.project_id, "props": {"name": p.name}} for p in projects])

    merge_edges(client, ns, "WORKS_FOR", "Person", "Customer", [_edge(p.contact_id, p.customer_id) for p in contacts])
    merge_edges(client, ns, "HOLDS", "Customer", "Contract", [_edge(k.customer_id, k.contract_id) for k in contracts])
    merge_edges(client, ns, "COVERS", "Contract", "PricingCategory", [
        _edge(k.contract_id, category) for k in contracts for category in k.covered_categories
    ])
    merge_edges(client, ns, "IN_FAMILY", "SKU", "ProductFamily", [_edge(s.sku_id, s.family_id) for s in skus if s.family_id])
    merge_edges(client, ns, "REPLACED_BY", "SKU", "SKU", [_edge(s.sku_id, s.replaced_by) for s in skus if s.replaced_by])
    merge_edges(client, ns, "PRICED_IN", "SKU", "PricingCategory", [_edge(s.sku_id, s.category) for s in skus])
    merge_edges(client, ns, "REQUIRES", "SKU", "SKU", [
        _edge(r.sku_id, r.required_sku_id) for r in all_requirements(session)
    ])
    merge_edges(client, ns, "HAS_PROJECT", "Customer", "Project", [_edge(p.customer_id, p.project_id) for p in projects])
    merge_edges(client, ns, "AT_SITE", "Project", "Site", [_edge(p.project_id, p.site_id) for p in projects])

    merge_nodes(client, ns, "GraphMeta", [{"id": ns, "props": {
        "reference_fingerprint": reference_fingerprint(session),
        "built_at": datetime.now(timezone.utc).isoformat(),
    }}])
