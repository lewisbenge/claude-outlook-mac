from src.main import build_parser


def test_parser_defaults():
    args = build_parser().parse_args([])
    assert args.limit == 50
