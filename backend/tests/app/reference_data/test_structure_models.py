import pytest
from sqlalchemy.exc import IntegrityError

from app.reference_data.models import Contact, Customer, ProductFamily, Project, Site, Sku
from app.retrieval.models import CommunitySummary, SkuEmbedding


def _customer(session, customer_id="CUST-SM1"):
    session.add(Customer(customer_id=customer_id, name="n", account_tier="Standard"))
    session.flush()


def test_family_project_and_contact_round_trip(db_session):
    _customer(db_session)
    db_session.add(Site(site_id="SITE-SM1", customer_id="CUST-SM1", address="1 Main St", zip="00000"))
    db_session.add(ProductFamily(family_id="FAM-SM1", name="Copper Adapter", category="Cat-SM"))
    db_session.flush()
    db_session.add(Project(project_id="PRJ-SM1", customer_id="CUST-SM1", site_id="SITE-SM1", name="job"))
    db_session.add(Contact(contact_id="CUST-SM1-C1", customer_id="CUST-SM1", name="Ravi", email="r@x.example", phone="555"))
    db_session.flush()

    assert db_session.get(Project, "PRJ-SM1").site_id == "SITE-SM1"
    assert db_session.get(Contact, "CUST-SM1-C1").email == "r@x.example"
    assert db_session.get(ProductFamily, "FAM-SM1").category == "Cat-SM"


def test_a_site_can_host_only_one_project(db_session):
    _customer(db_session)
    db_session.add(Site(site_id="SITE-SM2", customer_id="CUST-SM1", address="2 Main St", zip="00000"))
    db_session.flush()
    db_session.add(Project(project_id="PRJ-SM2", customer_id="CUST-SM1", site_id="SITE-SM2", name="a"))
    db_session.flush()

    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            db_session.add(Project(project_id="PRJ-SM3", customer_id="CUST-SM1", site_id="SITE-SM2", name="b"))
            db_session.flush()


def test_sku_family_link(db_session):
    db_session.add(ProductFamily(family_id="FAM-SM4", name="F", category="Cat-SM"))
    db_session.flush()
    db_session.add(Sku(sku_id="SKU-SM4", name="F 1 in", category="Cat-SM", list_price=1.0, discontinued=False,
                       replaced_by=None, in_stock=True, family_id="FAM-SM4"))
    db_session.flush()

    assert db_session.get(Sku, "SKU-SM4").family_id == "FAM-SM4"


def test_embedding_and_summary_round_trip(db_session):
    db_session.add(Sku(sku_id="SKU-SM5", name="n", category="Cat-SM", list_price=1.0, discontinued=False,
                       replaced_by=None, in_stock=True))
    db_session.flush()
    db_session.add(SkuEmbedding(sku_id="SKU-SM5", embedding=[0.5] * 1536, model="test-model"))
    db_session.add(CommunitySummary(member_hash="hash-sm5", summary="A cluster.", model="test-model"))
    db_session.flush()
    db_session.expire_all()

    assert list(db_session.get(SkuEmbedding, "SKU-SM5").embedding)[:2] == [0.5, 0.5]
    assert db_session.get(CommunitySummary, "hash-sm5").summary == "A cluster."
