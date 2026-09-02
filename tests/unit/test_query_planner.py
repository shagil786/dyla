from dyla.domain import MemoryRecord
from dyla.query_planner import QueryPlanner


def test_expand_is_one_step_bounded_and_removes_duplicate_queries():
    class Model:
        def complete(self, request):
            raise AssertionError("planner should not need a model for deterministic expansion")

    planner = QueryPlanner(max_subqueries=2)
    plan = planner.expand(
        "What changed for Acme in 2025?",
        [MemoryRecord(id="m1", kind="fact", text="Acme launched a product", entity_ids=["acme"], source_ids=[], verified=True)],
    )

    assert plan.original_question == "What changed for Acme in 2025?"
    assert len(plan.subqueries) <= 2
    queries = [item["query"] for item in plan.subqueries]
    assert len(queries) == len(set(queries))
    assert any("Acme" in query for query in queries)
    assert plan.entities == ["Acme"]
    assert plan.date_constraints == ["2025"]


def test_expand_traces_original_generated_queries_and_cap():
    events = []
    class Writer:
        def append(self, event):
            events.append(event)

    planner = QueryPlanner(max_subqueries=2, trace_writer=Writer(), run_id="run-9")
    plan = planner.expand("What changed for Acme in 2025?", [
        MemoryRecord(id="m1", kind="fact", text="Acme launched a product", entity_ids=["e1"], source_ids=[], verified=True)
    ])
    assert events[0].run_id == "run-9"
    assert events[0].event == "query_expanded"
    assert events[0].payload == {"original_query": "What changed for Acme in 2025?", "queries": [item["query"] for item in plan.subqueries], "cap": 2}


def test_expand_accepts_structured_model_output_but_does_not_expand_expansions():
    class Model:
        def __init__(self):
            self.calls = 0

        def complete(self, request):
            self.calls += 1
            return type("Response", (), {"parsed": type("Plan", (), {
                "original_question": "Q", "subqueries": [
                    {"query": "Q", "purpose": "baseline"},
                    {"query": "Q", "purpose": "duplicate"},
                    {"query": "Q2", "purpose": "context"},
                ], "entities": ["Acme"], "date_constraints": ["2024"]
            })()})()

    model = Model()
    plan = QueryPlanner(model=model, max_subqueries=2).expand("Q", [])

    assert model.calls == 1
    assert [item["query"] for item in plan.subqueries] == ["Q", "Q2"]
