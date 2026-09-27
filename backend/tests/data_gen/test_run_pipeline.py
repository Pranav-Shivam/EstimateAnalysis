from data_gen.catalog_gen import generate_catalog
from data_gen.config import DEFAULT
from data_gen.customer_gen import generate_customers
from data_gen.run_pipeline import check_output_paths_are_clear
from data_gen.validate import check_determinism


def test_check_output_paths_are_clear_passes_when_nothing_exists(tmp_path):
    paths = [tmp_path / "catalog.json", tmp_path / "customers.json"]
    check_output_paths_are_clear(paths, force=False)  # must not raise


def test_check_output_paths_are_clear_fails_if_any_path_exists(tmp_path):
    existing = tmp_path / "catalog.json"
    existing.write_text("{}")
    paths = [existing, tmp_path / "customers.json"]
    try:
        check_output_paths_are_clear(paths, force=False)
        assert False, "expected FileExistsError"
    except FileExistsError as e:
        assert "catalog.json" in str(e)


def test_check_output_paths_are_clear_allows_force(tmp_path):
    existing = tmp_path / "catalog.json"
    existing.write_text("{}")
    paths = [existing, tmp_path / "customers.json"]
    check_output_paths_are_clear(paths, force=True)  # must not raise


def test_data_dir_default_resolves_to_backend_data_regardless_of_cwd():
    from data_gen.run_pipeline import DATA_DIR
    assert DATA_DIR.name == "data"
    assert DATA_DIR.parent.name == "backend"


def test_full_pipeline_is_deterministic():
    def regenerate():
        catalog = generate_catalog(DEFAULT)
        customers = generate_customers(DEFAULT, catalog)
        return catalog, customers

    assert check_determinism(regenerate) == []
