from rest_framework import serializers


class DueSurveySerializer(serializers.Serializer):
    """Serializes a (survey, due_date) pair from research.models.due_surveys."""

    def to_representation(self, instance):
        survey, due_date = instance
        return {
            "id": survey.id,
            "title": survey.title,
            "description": survey.description,
            "study": survey.study.name,
            "due_date": due_date.isoformat(),
            "url": survey.link_for(self.context["request"].user),
        }
