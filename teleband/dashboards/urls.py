from django.urls import path

from teleband.dashboards.views import (
    AssignmentListView,
    CourseListView,
    ResearchDashboardView,
    attachment_proxy_view,
    csv_view,
    research_data_view,
)

app_name = "dashboards"
urlpatterns = [
    path("", AssignmentListView.as_view(), name="assignment_list"),
    path("courses/", CourseListView.as_view(), name="course_list"),
    path("export/csv/", csv_view, name="export_csv"),
    path("research/", ResearchDashboardView.as_view(), name="research"),
    path("research/data/", research_data_view, name="research_data"),
    path(
        "research/attachment/<int:attachment_id>/",
        attachment_proxy_view,
        name="attachment_proxy",
    ),
]
