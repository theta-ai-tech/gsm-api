from app.models.enums import BroadcastTypeEnum, MatchTypeEnum


class TestMatchTypeEnum:
    def test_values(self) -> None:
        assert MatchTypeEnum.SINGLES == "singles"
        assert MatchTypeEnum.DOUBLES == "doubles"

    def test_all_members(self) -> None:
        assert len(MatchTypeEnum) == 2

    def test_membership(self) -> None:
        assert "singles" in {e.value for e in MatchTypeEnum}
        assert "doubles" in {e.value for e in MatchTypeEnum}

    def test_string_round_trip(self) -> None:
        assert MatchTypeEnum("singles") is MatchTypeEnum.SINGLES
        assert MatchTypeEnum("doubles") is MatchTypeEnum.DOUBLES

    def test_is_str_subclass(self) -> None:
        # StrEnum members compare equal to their string value
        assert isinstance(MatchTypeEnum.SINGLES, str)
        assert isinstance(MatchTypeEnum.DOUBLES, str)


class TestBroadcastTypeEnum:
    def test_values(self) -> None:
        assert BroadcastTypeEnum.FIND_OPPONENT == "find_opponent"
        assert BroadcastTypeEnum.FIND_FOURTH == "find_fourth"

    def test_all_members(self) -> None:
        assert len(BroadcastTypeEnum) == 2

    def test_membership(self) -> None:
        assert "find_opponent" in {e.value for e in BroadcastTypeEnum}
        assert "find_fourth" in {e.value for e in BroadcastTypeEnum}

    def test_string_round_trip(self) -> None:
        assert BroadcastTypeEnum("find_opponent") is BroadcastTypeEnum.FIND_OPPONENT
        assert BroadcastTypeEnum("find_fourth") is BroadcastTypeEnum.FIND_FOURTH

    def test_is_str_subclass(self) -> None:
        assert isinstance(BroadcastTypeEnum.FIND_OPPONENT, str)
        assert isinstance(BroadcastTypeEnum.FIND_FOURTH, str)
