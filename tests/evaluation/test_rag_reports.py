from verbaops.evaluation.rag_reports import percentile, serialize_report


def test_rag_report_serialization_has_stable_shape_and_percentiles() -> None:
    assert percentile([1, 2, 3, 4], 0.95) == 3.85
    assert percentile([], 0.5) is None
    report = serialize_report({"dataset_version": "rag-v0.1", "metrics": {"recall_at_5": 0.9}})
    assert report["dataset_version"] == "rag-v0.1"
