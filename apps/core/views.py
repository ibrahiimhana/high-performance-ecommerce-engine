from django.conf import settings
from django.db import connection
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response


@api_view(["GET"])
@permission_classes([AllowAny])
def health(_request):
    """Cheap health probe. Used by the load-distribution demo."""
    try:
        with connection.cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
        db_ok = True
    except Exception:  # pragma: no cover
        db_ok = False
    return Response({
        "status": "ok" if db_ok else "degraded",
        "instance": settings.INSTANCE_NAME,
        "db": db_ok,
    })
