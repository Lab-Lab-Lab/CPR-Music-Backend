from rest_framework import serializers


class DueSurveySerializer(serializers.Serializer):
    """Serializes a (survey, participant, due_date) row from services.due_surveys."""

    def to_representation(self, instance):
        survey, participant, due_date = instance
        return {
            "id": survey.id,
            "title": survey.title,
            "description": survey.description,
            "study": survey.study.name,
            "due_date": due_date.isoformat(),
            "url": survey.link_for(participant),
        }
