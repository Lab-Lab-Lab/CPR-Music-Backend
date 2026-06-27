"""Query-count regression test for the CSV export dashboard (Phase 1a #11).

The CSV export streams the entire Assignment table unfiltered, so the right
guarantee is that it issues O(1) queries, not O(rows). The test DB is seeded with
thousands of assignments by a data migration; this asserts the export stays under
a small constant ceiling regardless, which only holds if every relation the row
loop (and the Activity/PiecePlan __str__) walks is select_related/prefetched.
"""

import pytest
from django.test.utils import CaptureQueriesContext
from django.db import connection
from django.test import Client

from teleband.assignments.tests.factories import AssignmentFactory
from teleband.musics.tests.factories import PartFactory, PieceFactory
from teleband.submissions.models import SubmissionAttachment
from teleband.submissions.tests.factories import SubmissionFactory

pytestmark = pytest.mark.django_db

# Generous ceiling: the export should be a handful of queries (base + one per
# prefetched relation, chunked). Anything near the row count is an N+1.
MAX_QUERIES = 25


def test_csv_export_is_constant_query_count():
    # Add some assignments that exercise the nested (has-submissions) branch on
    # top of the seeded rows that exercise the empty branch.
    piece = PieceFactory()
    for _ in range(10):
        part = PartFactory(piece=piece)
        assignment = AssignmentFactory(part=part, piece=piece)
        submission = SubmissionFactory(assignment=assignment)
        SubmissionAttachment.objects.create(submission=submission, file="a.wav")

    client = Client()
    with CaptureQueriesContext(connection) as ctx:
        response = client.get("/dashboards/export/csv/")
    assert response.status_code == 200

    n = len(ctx.captured_queries)
    assert n <= MAX_QUERIES, (
        f"CSV export issued {n} queries (ceiling {MAX_QUERIES}) -- N+1 regression: "
        f"the export should be O(1) in queries, not O(rows)."
    )
