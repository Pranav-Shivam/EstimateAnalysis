import seed_demo


def test_dry_run_and_replay_flags_parse():
    args = seed_demo.parse_args(["--yes", "--replay"])

    assert args.yes is True
    assert args.replay is True
    assert seed_demo.parse_args([]).yes is False
