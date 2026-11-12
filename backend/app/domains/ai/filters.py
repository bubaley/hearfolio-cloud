from fastapi_ronin import filters

from app.domains.ai.models import SummaryTemplate


class SummaryTemplateFilterSet(filters.FilterSet):
    fields = (
        filters.CharFilter('name', view_name='search', default_lookup='icontains'),
        filters.BooleanFilter('auto'),
    )

    class Meta:
        model = SummaryTemplate
