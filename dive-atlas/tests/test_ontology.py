from dive_atlas.ontology import CertLevel, OverheadClass, PhenomenonType, RouteKind
from dive_atlas.services.trip import TripRequest


def test_ontology_covers_product_surface():
    assert CertLevel.AOW.value == "aow"
    assert CertLevel.FULL_CAVE.value == "full_cave"
    assert OverheadClass.CAVE.value == "cave"
    assert PhenomenonType.SARDINE_RUN.value == "sardine_run"
    assert RouteKind.CENOTE_SPINE.value == "cenote_spine"


def test_trip_request_defaults():
    req = TripRequest(want=["caves", "pelagics"], max_depth_m=30)
    assert req.days == 10
    assert "aow" in req.certs
    assert req.avoid_monsoon is True
