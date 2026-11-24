"""C14 end to end on the oracle (17 sessions): job -> run -> verdict `inconclusive`, labels, reruns."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from nifty.worker import process_one
from tests.conftest import ORIGIN
from tests.helpers import ORACLE

pytestmark = pytest.mark.db
H = {"Origin": ORIGIN}
BODY = {"symbol": "NIFTY 50", "experiments": [10, 20], "cost_pts": 1.0, "seed": 5}


def load(c: TestClient) -> None:
    r = c.post("/api/v1/datasets/import?symbol=NIFTY 50&tick_size=0.05", content=ORACLE.read_bytes(),
               headers={**H, "Content-Type": "text/csv"})  # fmt: skip
    assert r.status_code == 200


def test_oracle_run_is_inconclusive_and_idempotent(api: tuple[TestClient, Engine]) -> None:
    c, eng = api
    load(c)
    assert (
        c.post("/api/v1/research/runs", json={**BODY, "variants": ["nope"]}, headers=H).status_code
        == 422
    )
    r = c.post("/api/v1/research/runs", json=BODY, headers=H)
    assert r.status_code == 202
    assert process_one(eng) is True
    job = c.get(f"/api/v1/jobs/{r.json()['job_id']}").json()
    assert job["status"] == "done", job
    rid = job["result_ref"]
    run = c.get(f"/api/v1/research/runs/{rid}").json()
    assert run["status"] == "done" and run["verdict"] == "inconclusive"
    assert "insufficient sessions" in run["result"]["verdict"]["reason"]
    assert (
        run["result"]["n_sessions"] == 17 and len(run["result"]["cells"]) == 8
    )  # 4 variants x 2 targets
    assert [len(run["splits"][k]) for k in ("dev", "val", "eval")] == [9, 4, 4]
    for cell in run["result"]["cells"]:
        assert cell["verdict"]["verdict"] == "inconclusive"
    n = c.get(f"/api/v1/research/runs/{rid}/labels?limit=500").json()
    assert n and all(
        x["label"].startswith(("BEARISH INDEX / PUT", "BULLISH INDEX / CALL")) for x in n
    )
    assert all(x["trade"]["execution_mode"] == "conservative" for x in n)
    # same inputs => same run, no duplicate labels
    with eng.connect() as k:
        before = k.execute(text("select count(*) from research_labels")).scalar()
    again = c.post("/api/v1/research/runs", json=BODY, headers=H).json()
    assert again["job_id"] == r.json()["job_id"] and again["result_ref"] == rid
    from nifty.db.research import run_research

    with eng.begin() as k:
        assert run_research(k, BODY) == rid
    with eng.connect() as k:
        assert k.execute(text("select count(*) from research_labels")).scalar() == before
    assert [x["research_id"] for x in c.get("/api/v1/research/runs").json()] == [rid]


def test_resume_skips_finished_cells(api: tuple[TestClient, Engine]) -> None:
    c, eng = api
    load(c)
    from nifty.db.research import run_research

    with eng.begin() as k:
        rid = run_research(k, BODY)
    full = c.get(f"/api/v1/research/runs/{rid}").json()["result"]
    with eng.begin() as k:  # simulate a crash after 3 cells
        k.execute(text("update research_runs set status='running', result=null, progress = "
                       "(select jsonb_object_agg(key, value) from (select * from jsonb_each(progress) limit 3) t)"))  # fmt: skip
        k.execute(text("delete from research_labels where variant || experiment not in "
                       "(select value->>'variant' || 'target_' || trim(trailing '.0' from (value->>'experiment')) from research_runs, jsonb_each(progress))"))  # fmt: skip
    with eng.begin() as k:
        assert run_research(k, BODY) == rid
    assert c.get(f"/api/v1/research/runs/{rid}").json()["result"] == full


def test_failure_is_stored_not_an_empty_success(api: tuple[TestClient, Engine]) -> None:
    c, eng = api
    r = c.post("/api/v1/research/runs", json={"symbol": "NOPE"}, headers=H)
    assert process_one(eng) is True
    job = c.get(f"/api/v1/jobs/{r.json()['job_id']}").json()
    assert job["status"] == "failed" and "unknown symbol" in job["error"]
