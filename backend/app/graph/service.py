import logging
import uuid
from collections import Counter
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.dedupe.repository import all_verdict_request_ids, verdicts_for_request
from app.estimate.models import EstimateDraftRow
from app.estimate.repository import all_estimate_draft_ids, get_estimate_draft, previous_estimate_draft
from app.graph.constant import (
    LABEL_LIST_LIMIT, LOCAL_MAX_HOPS, LOCAL_MAX_NODES, NEIGHBOR_LIMIT, SEARCH_LIMIT, VARIANT_MIN_JACCARD,
)
from app.graph.helper import build_community_stats, match_site
from app.graph.lock import try_lock_rebuild, unlock_rebuild
from app.graph.repository import (
    advance_fingerprint, clear_communities, count_edges_between_labels, count_edges_by_type, count_nodes_by_label,
    drop_namespace, ensure_constraints, fetch_all_edges, fetch_all_nodes, list_nodes_by_label,
    fetch_community_members, fetch_local_paths, fetch_neighborhood, fetch_node, merge_edges, merge_nodes,
    replace_price_variance, run_leiden, search_nodes, write_communities,
)
from app.graph.schemas import CommunityRunSummary, CommunityStats, LocalResult, RebuildSummary
from app.intake.models import QuoteRequestRow
from app.intake.repository import all_quote_request_ids, get_quote_request
from app.reference_data.repository import (
    all_contacts, all_contracts, all_customers, all_families, all_projects, all_requirements, all_sites, all_skus,
    get_sku, project_for_site, reference_fingerprint, sites_for_customer,
)
from core.graph.client import GraphClient, GraphError

logger = logging.getLogger(__name__)


def _edge(source: str, target: str) -> dict:
    return {"from": source, "to": target, "props": {}}


def rebuild_reference_graph(session: Session, client: GraphClient, ns: str) -> str:
    """Wipe and reload the reference part of one namespace from Postgres. Idempotent. Returns the fingerprint it
    stamped."""
    # Taken before any reference row is read. Each read sees whatever is committed when it runs, so a correction
    # committed mid-rebuild may or may not be in the graph; stamping the earlier state makes the graph read as
    # stale in that case (a rebuild repairs it) instead of current while possibly missing the correction.
    fingerprint = reference_fingerprint(session)
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
        "reference_fingerprint": fingerprint, "built_at": datetime.now(timezone.utc).isoformat(),
    }}])
    return fingerprint


def _created_at(row) -> str | None:
    return row.created_at.isoformat() if row.created_at else None


def _project_for_request(session: Session, row: QuoteRequestRow) -> str | None:
    site_id = row.site_id
    if site_id is None:
        hint = (row.parsed_json.get("extraction") or {}).get("site_hint")
        if not hint or row.customer_id is None:
            return None
        site_id = match_site(hint, sites_for_customer(session, row.customer_id))
    if site_id is None:
        return None
    project = project_for_site(session, site_id)
    return project.project_id if project else None


def sync_quote_request(session: Session, client: GraphClient, ns: str, quote_request_id: uuid.UUID) -> None:
    row = get_quote_request(session, quote_request_id)
    if row is None:
        raise ValueError(f"quote request {quote_request_id} not found")
    merge_nodes(client, ns, "QuoteRequest", [
        {"id": str(row.id), "props": {"case_id": row.case_id, "created_at": _created_at(row)}},
    ])
    project_id = _project_for_request(session, row)
    if project_id is not None:
        merge_edges(client, ns, "FOR_PROJECT", "QuoteRequest", "Project", [_edge(str(row.id), project_id)])


def _verdict_edge_type(verdict, target: QuoteRequestRow, candidate: QuoteRequestRow) -> str | None:
    if verdict.verdict in ("DUPLICATE_OF", "REVISION_OF"):
        return verdict.verdict
    same_customer = target.customer_id is not None and target.customer_id == candidate.customer_id
    if verdict.verdict == "DISTINCT" and same_customer and verdict.content_jaccard >= VARIANT_MIN_JACCARD:
        return "VARIANT_OF"
    return None


def sync_dedupe_verdicts(session: Session, client: GraphClient, ns: str, quote_request_id: uuid.UUID) -> None:
    verdicts = verdicts_for_request(session, quote_request_id)
    if not verdicts:
        return
    target = get_quote_request(session, quote_request_id)
    sync_quote_request(session, client, ns, quote_request_id)
    rows_by_type: dict[str, list[dict]] = {}
    for verdict in verdicts:
        candidate = get_quote_request(session, verdict.candidate_quote_request_id)
        edge_type = _verdict_edge_type(verdict, target, candidate)
        if edge_type is None:
            continue
        sync_quote_request(session, client, ns, candidate.id)
        rows_by_type.setdefault(edge_type, []).append({
            "from": str(target.id), "to": str(candidate.id), "props": {"content_jaccard": verdict.content_jaccard},
        })
    for edge_type, rows in rows_by_type.items():
        merge_edges(client, ns, edge_type, "QuoteRequest", "QuoteRequest", rows)


def _merge_quote_node(client: GraphClient, ns: str, row: EstimateDraftRow) -> None:
    merge_nodes(client, ns, "Quote", [{"id": str(row.id), "props": {
        "quote_request_id": str(row.quote_request_id), "status": row.status, "created_at": _created_at(row),
    }}])


def _price_variance_rows(session: Session, row: EstimateDraftRow) -> list[dict]:
    rows = []
    for index, line in enumerate((row.draft or {}).get("lines", [])):
        sku_id = line.get("sku_id")
        discount = line.get("discount_pct") or 0.0
        source = line.get("price_source")
        if sku_id is None or (discount == 0 and source != "predicted"):
            continue
        unit_price = line.get("unit_price")
        sku = get_sku(session, sku_id)
        rows.append({"sku_id": sku_id, "props": {
            "line_index": index, "list_price": sku.list_price if sku else None, "unit_price": unit_price,
            "discount_pct": discount, "price_source": source,
            "net_unit_price": round(unit_price * (1 - discount / 100), 4) if unit_price is not None else None,
        }})
    return rows


def sync_quote(session: Session, client: GraphClient, ns: str, estimate_id: uuid.UUID) -> None:
    row = get_estimate_draft(session, estimate_id)
    if row is None:
        raise ValueError(f"estimate draft {estimate_id} not found")
    _merge_quote_node(client, ns, row)
    previous = previous_estimate_draft(session, row)
    if previous is not None:
        _merge_quote_node(client, ns, previous)
        merge_edges(client, ns, "SUPERSEDES", "Quote", "Quote", [_edge(str(row.id), str(previous.id))])
    replace_price_variance(client, ns, str(row.id), _price_variance_rows(session, row))


def sync_sku(session: Session, client: GraphClient, ns: str, sku_id: str) -> None:
    sku = get_sku(session, sku_id)
    if sku is None:
        return
    merge_nodes(client, ns, "SKU", [{"id": sku.sku_id, "props": {
        "name": sku.name, "category": sku.category, "list_price": sku.list_price,
        "discontinued": sku.discontinued, "in_stock": sku.in_stock,
    }}])


class GraphSyncIncomplete(GraphError):
    """A single-fact sync could not write its edge because an endpoint node is not in the graph."""


def _merge_one_edge(client: GraphClient, ns: str, edge_type: str, from_label: str, to_label: str, source: str,
                    target: str) -> None:
    if merge_edges(client, ns, edge_type, from_label, to_label, [_edge(source, target)]) == 0:
        raise GraphSyncIncomplete(f"no {from_label} {source} or no {to_label} {target} in graph namespace {ns}")


def _advance_graph_meta(session: Session, client: GraphClient, ns: str, previous_fingerprint: str) -> None:
    """Corrections to SkuRequirement or Contract.covered_categories change reference_fingerprint(); without this,
    graph_is_current() would see the graph as stale after every correction and block every future estimate.

    The new fingerprint is stamped only if the graph was current before this correction (it still holds
    `previous_fingerprint`, read before the Postgres write). A graph already stale, from an earlier failed sync
    or a rebuild still loading, holds some other value or no GraphMeta at all, and must stay stale until a rebuild:
    stamping it would mark current a graph that is missing some other fact."""
    advanced = advance_fingerprint(
        client, ns, previous_fingerprint, reference_fingerprint(session), datetime.now(timezone.utc).isoformat(),
    )
    if not advanced:
        logger.warning("graph namespace %s was already stale; left stale, run a rebuild to repair it", ns)


def sync_requirement(
    session: Session, client: GraphClient, ns: str, sku_id: str, required_sku_id: str, previous_fingerprint: str,
) -> None:
    _merge_one_edge(client, ns, "REQUIRES", "SKU", "SKU", sku_id, required_sku_id)
    _advance_graph_meta(session, client, ns, previous_fingerprint)


def sync_contract_coverage(
    session: Session, client: GraphClient, ns: str, contract_id: str, category: str, previous_fingerprint: str,
) -> None:
    merge_nodes(client, ns, "PricingCategory", [{"id": category, "props": {}}])
    _merge_one_edge(client, ns, "COVERS", "Contract", "PricingCategory", contract_id, category)
    _advance_graph_meta(session, client, ns, previous_fingerprint)


class GraphRebuildInProgress(Exception):
    pass


def rebuild_graph(session: Session, client: GraphClient, ns: str) -> RebuildSummary:
    """Reload the whole namespace, runtime entities included, from Postgres. Two overlapping rebuilds of one
    namespace could leave a half-loaded graph carrying a current fingerprint, so only one may run at a time."""
    if not try_lock_rebuild(session, ns):
        raise GraphRebuildInProgress(f"a rebuild of graph namespace {ns} is already running")
    try:
        fingerprint = rebuild_reference_graph(session, client, ns)
        for request_id in all_quote_request_ids(session):
            sync_quote_request(session, client, ns, request_id)
        for request_id in all_verdict_request_ids(session):
            sync_dedupe_verdicts(session, client, ns, request_id)
        for estimate_id in all_estimate_draft_ids(session):
            sync_quote(session, client, ns, estimate_id)
        return RebuildSummary(
            namespace=ns, fingerprint=fingerprint,
            node_counts=count_nodes_by_label(client, ns), edge_counts=count_edges_by_type(client, ns),
        )
    finally:
        unlock_rebuild(session, ns)


def sync_best_effort(description: str, sync, *args) -> None:
    """Run a sync after Postgres has committed. The graph is derived, so a failure is logged and a rebuild repairs
    it; it must never fail the request that already succeeded."""
    try:
        sync(*args)
    except GraphError:
        logger.warning("graph sync failed for %s; run a rebuild to repair the graph", description, exc_info=True)


class NodeNotFound(Exception):
    pass


def run_communities(client: GraphClient, ns: str) -> CommunityRunSummary:
    assignments = run_leiden(client, ns)
    clear_communities(client, ns)
    write_communities(client, ns, assignments)
    sku_sizes = Counter(a["community"] for a in assignments if a["label"] == "SKU")
    return CommunityRunSummary(
        community_count=len(sku_sizes), largest_community_size=max(sku_sizes.values(), default=0),
    )


def global_stats(client: GraphClient, ns: str) -> list[CommunityStats]:
    return build_community_stats(fetch_community_members(client, ns))


def local_query(client: GraphClient, ns: str, node_id: str, hops: int = LOCAL_MAX_HOPS) -> LocalResult:
    center = fetch_node(client, ns, node_id)
    if center is None:
        raise NodeNotFound(f"no node {node_id} in the graph")
    hops = max(1, min(int(hops), LOCAL_MAX_HOPS))

    nodes: dict[str, dict] = {center["id"]: center}
    truncated = False
    kept_paths = []
    for row in fetch_local_paths(client, ns, node_id, hops):
        new = [n for n in row["nodes"] if n["id"] not in nodes]
        # A path is added whole or not at all, so the result never holds a node cut off from the centre.
        if len(nodes) + len(new) > LOCAL_MAX_NODES:
            truncated = True
            continue
        nodes.update({n["id"]: n for n in new})
        kept_paths.append(row)

    edges: dict[tuple[str, str, str], dict] = {}
    for row in kept_paths:
        for edge in row["edges"]:
            edges[(edge["source"], edge["type"], edge["target"])] = edge
    return LocalResult(center=node_id, nodes=list(nodes.values()), edges=list(edges.values()), truncated=truncated)


class GraphNodeNotFound(Exception):
    pass


def search(client: GraphClient, ns: str, text: str) -> list[dict]:
    return search_nodes(client, ns, text.strip(), SEARCH_LIMIT)


def neighborhood(client: GraphClient, ns: str, node_id: str) -> dict:
    found = fetch_neighborhood(client, ns, node_id, NEIGHBOR_LIMIT)
    if found is None:
        raise GraphNodeNotFound(node_id)
    rows = found["rows"][:NEIGHBOR_LIMIT]
    nodes = {r["id"]: {key: r[key] for key in ("id", "label", "name", "community")} for r in rows}
    edges = [{"source": r["source"], "target": r["target"], "type": r["type"]} for r in rows]
    return {
        "center": found["center"], "nodes": list(nodes.values()), "edges": edges,
        "truncated": len(found["rows"]) > NEIGHBOR_LIMIT,
    }


def schema_stats(client: GraphClient, ns: str) -> dict:
    return {"node_counts": count_nodes_by_label(client, ns), "edge_counts": count_edges_by_type(client, ns)}


def schema_overview(client: GraphClient, ns: str) -> dict:
    counts = {label: n for label, n in count_nodes_by_label(client, ns).items() if label != "GraphMeta"}
    return {"node_counts": counts, "edges": count_edges_between_labels(client, ns)}


def nodes_of_label(client: GraphClient, ns: str, label: str) -> dict:
    rows = list_nodes_by_label(client, ns, label, LABEL_LIST_LIMIT + 1)
    return {"nodes": rows[:LABEL_LIST_LIMIT], "truncated": len(rows) > LABEL_LIST_LIMIT}


def full_graph(client: GraphClient, ns: str) -> dict:
    return {"nodes": fetch_all_nodes(client, ns), "edges": fetch_all_edges(client, ns)}
