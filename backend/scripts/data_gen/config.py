import dataclasses


@dataclasses.dataclass(frozen=True)
class Config:
    seed: int
    sku_count: int
    customer_count: int
    scenarios_per_type: int


DEFAULT = Config(seed=42, sku_count=650, customer_count=125, scenarios_per_type=10)


def validate_config(config: Config) -> None:
    if config.seed is None:
        raise ValueError("seed must be set")
    if config.sku_count <= 0:
        raise ValueError("sku_count must be positive")
    if not (500 <= config.sku_count <= 800):
        raise ValueError("sku_count must be in [500, 800]")
    if config.customer_count <= 0:
        raise ValueError("customer_count must be positive")
    if not (100 <= config.customer_count <= 150):
        raise ValueError("customer_count must be in [100, 150]")
    if config.scenarios_per_type <= 0:
        raise ValueError("scenarios_per_type must be positive")
    if config.scenarios_per_type != 10:
        raise ValueError("scenarios_per_type must be exactly 10")
