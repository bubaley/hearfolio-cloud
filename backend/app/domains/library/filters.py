from fastapi_ronin import filters

from app.domains.library.models import Project, Tag


class ProjectFilterSet(filters.FilterSet):
    fields = (
        filters.CharFilter('name', default_lookup='icontains'),
        filters.BooleanFilter('is_private'),
        filters.BooleanFilter(
            'archived_at', view_name='archived', lookups=['isnull'], default_lookup='not_isnull', exclude=True
        ),
    )

    class Meta:
        model = Project


class TagFilterSet(filters.FilterSet):
    fields = (filters.CharFilter('name', default_lookup='icontains'),)

    class Meta:
        model = Tag
