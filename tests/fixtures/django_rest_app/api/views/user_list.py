from api.pagination import CursorPaginator
from api.serializers.user import UserSerializer


def list_users(request):
    paginator = CursorPaginator(cursor=request.GET.get("cursor"))
    users = paginator.page()
    return [UserSerializer(user).data for user in users]
