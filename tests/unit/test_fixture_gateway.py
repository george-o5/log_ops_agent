import pytest

from logops.errors import ConnectError, IntegrationError, SearchError, UnsupportedOperation
from logops.gateway import SplunkGateway
from logops.gateway.fixture import FixtureGateway
from logops.models import DataSource, IndexInfo, SavedSearch, SearchResult


def test_fixture_satisfies_protocol() -> None:
    assert isinstance(FixtureGateway(), SplunkGateway)
    assert FixtureGateway().source is DataSource.FIXTURE


async def test_missing_index_is_data_not_error() -> None:
    gw = FixtureGateway(indexes={"main": IndexInfo(name="main", exists=True, total_event_count=10)})
    assert (await gw.describe_index("main")).exists
    ghost = await gw.describe_index("ghost_network_logs")
    assert ghost.exists is False


async def test_configured_failure_raises_typed_error() -> None:
    gw = FixtureGateway(
        saved_searches=[SavedSearch(id="1", name="n", search="s")],
        failures={"list_saved_searches": ConnectError("refused")},
    )
    with pytest.raises(IntegrationError) as exc:
        await gw.list_saved_searches()
    assert exc.value.kind == "connect"


async def test_search_error_is_not_an_integration_error() -> None:
    gw = FixtureGateway(searches={"bad |": SearchError("syntax", spl="bad |")})
    with pytest.raises(SearchError):
        await gw.run_search("bad |", "-1h")


async def test_unknown_search_never_returns_fake_data() -> None:
    with pytest.raises(UnsupportedOperation):
        await FixtureGateway().run_search("index=main", "-1h")


async def test_max_rows_truncates() -> None:
    rows = tuple({"n": i} for i in range(5))
    gw = FixtureGateway(searches={"q": SearchResult(spl="q", earliest="-1h", latest="now", rows=rows)})
    r = await gw.run_search("q", "-1h", max_rows=2)
    assert r.row_count == 2
    assert r.truncated
    assert gw.calls[-1][0] == "run_search"
