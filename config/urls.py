from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema")),
    path("api/", include("apps.accounts.urls")),
    path("api/", include("apps.levels.urls")),
    path("api/", include("apps.snippets.urls")),
    path("api/", include("apps.progress.urls")),
    path("api/", include("apps.placement.urls")),
    path("api/", include("apps.vocabulary.urls")),
]
