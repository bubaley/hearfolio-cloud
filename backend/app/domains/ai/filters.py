from fastapi_ronin import filters

from app.domains.ai.models import RecordingResult, SummaryTemplate


class SummaryTemplateFilterSet(filters.FilterSet):
    fields = (
        filters.CharFilter('name', view_name='search', default_lookup='icontains'),
        filters.BooleanFilter('auto'),
    )

    class Meta:
        model = SummaryTemplate


class RecordingResultFilterSet(filters.FilterSet):
    fields = (
        filters.UUIDFilter('recording_id'),
        filters.CharFilter('status'),
        filters.DateTimeFilter('updated_at', view_name='updated_after', default_lookup='gt'),
    )

    class Meta:
        model = RecordingResult
